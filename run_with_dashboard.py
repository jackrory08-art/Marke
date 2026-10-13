#!/usr/bin/env python3
"""
Run Trading Bot with Dashboard
===============================

Starts the trading bot and web dashboard together.
Supports cross-platform arbitrage between Polymarket and Kalshi.

Usage:
    python run_with_dashboard.py                  # Dry run, http://127.0.0.1:8000
    python run_with_dashboard.py --port 8080      # Custom port
    python run_with_dashboard.py --host 0.0.0.0   # Bind all interfaces (use HTTPS in front)

Create the login first:  python -m app.create_user --username owner

Advisory tool: nothing here places orders. Live trading is disabled in this build.
"""

import argparse
import asyncio
import logging
import signal
import sys
import threading
from datetime import datetime

import uvicorn
from dotenv import load_dotenv

from polymarket_client import PolymarketClient
from kalshi_client import KalshiClient
from core.data_feed import DataFeed
from core.arb_engine import ArbEngine, ArbConfig
from core.execution import ExecutionEngine, ExecutionConfig
from core.risk_manager import RiskManager, RiskConfig
from core.portfolio import Portfolio
from core.cross_platform_arb import CrossPlatformArbEngine, MarketMatcher
from core.cross_platform_scanner import CrossPlatformScanner
from core.pair_store import PairInbox, PairStore
from core.market_ref import from_kalshi, from_polymarket
from predictit_client.api import build_predictit_client
from app import repo
from app.db import Database, init_database
from app.settings import apply_overrides
from utils.config_loader import load_config, validate_config, BotConfig
from utils.logging_utils import setup_logging
from dashboard.server import create_app, dashboard_state
from dashboard.integration import DashboardIntegration


logger = logging.getLogger(__name__)


class TradingBotWithDashboard:
    """Trading bot with integrated dashboard."""
    
    def __init__(self, config: BotConfig, host: str = "127.0.0.1", port: int = 8000):
        self.config = config
        self.host = host
        self.port = port
        self._running = False
        
        # Components - Polymarket
        self.client = None
        self.data_feed = None
        self.arb_engine = None
        self.execution_engine = None
        self.risk_manager = None
        self.portfolio = None
        self.dashboard_integration = None
        
        # Components - Kalshi (cross-platform)
        self.kalshi_client = None
        self.cross_platform_engine = None
        self.market_matcher = None
        self._kalshi_markets = []
        self._matched_pairs = []
        self._kalshi_entered = False
        self.predictit = None
        self.pair_store = PairStore()
        self.ai = None
        self.scanner = None
        self._scan_task = None
        self._background_tasks: list = []
        self.db: Database = None
        
        # Server
        self._server = None
        self._server_task = None
    
    async def start(self) -> None:
        """Start the bot and dashboard."""
        logger.info("=" * 60)
        logger.info("Polymarket + Kalshi Arbitrage Bot")
        logger.info("=" * 60)
        logger.info(f"Mode: {'DRY RUN' if self.config.is_dry_run else 'LIVE'}")
        logger.info(f"Cross-Platform: {'ENABLED' if self.config.mode.cross_platform_enabled else 'DISABLED'}")
        logger.info(f"Dashboard: http://{self.host}:{self.port}")
        logger.info("=" * 60)
        
        self._running = True
        
        # Database (users, sessions, verdicts, history) and persisted UI settings
        self.db = init_database(self.config.database.url, self.config.database.auto_migrate)
        apply_overrides(self.config, self.db)
        dashboard_state.paused = bool(self.config.mode.paused)
        if dashboard_state.paused:
            logger.info("Processing is PAUSED (resume it from the dashboard)")
        
        # Initialize Polymarket API client
        self.client = PolymarketClient(
            rest_url=self.config.api.polymarket_rest_url,
            ws_url=self.config.api.polymarket_ws_url,
            gamma_url=self.config.api.gamma_api_url,
            api_key=self.config.api.api_key,
            private_key=self.config.api.private_key,
            timeout=self.config.api.timeout_seconds,
            dry_run=self.config.is_dry_run,
        )
        await self.client.connect()
        
        # Simulation: a seeded demo of Kalshi/PredictIt pairs, no network needed
        if self.config.use_simulation and self.config.mode.cross_platform_enabled:
            self._start_simulated_cross_platform()
        # Initialize Kalshi client (if cross-platform enabled)
        elif self.config.mode.cross_platform_enabled and (
                self.config.mode.kalshi_enabled or self.config.predictit.enabled):
            if self.config.mode.kalshi_enabled:
                logger.info("Initializing Kalshi client for cross-platform arbitrage...")
                self.kalshi_client = KalshiClient(
                    timeout=self.config.api.timeout_seconds,
                    max_retries=self.config.api.max_retries,
                    dry_run=self.config.is_dry_run,
                )
            
            # Initialize cross-platform arbitrage engine
            self.cross_platform_engine = CrossPlatformArbEngine(
                min_edge=self.config.trading.min_edge,
                min_match_similarity=self.config.mode.min_match_similarity,
                min_edge_provider=lambda: self.config.trading.min_edge,
                predictit_min_net_edge=self.config.predictit.min_net_edge,
                predictit_max_contract_usd=self.config.predictit.max_contract_usd,
            )
            self.market_matcher = self.cross_platform_engine.matcher
            self._setup_cross_platform_services()
            
            # Start Kalshi monitoring in background
            if self.kalshi_client:
                self._background_tasks.append(asyncio.create_task(self._start_kalshi_monitoring()))
            
            # PredictIt (read-only, off by default)
            self._ensure_predictit()
        
        # Initialize portfolio
        initial_balance = (
            self.config.mode.dry_run_initial_balance 
            if self.config.is_dry_run 
            else 0.0
        )
        self.portfolio = Portfolio(initial_balance=initial_balance)
        
        # Initialize risk manager
        self.risk_manager = RiskManager(RiskConfig(
            max_position_per_market=self.config.risk.max_position_per_market,
            max_global_exposure=self.config.risk.max_global_exposure,
            max_daily_loss=self.config.risk.max_daily_loss,
            max_drawdown_pct=self.config.risk.max_drawdown_pct,
            trade_only_high_volume=self.config.risk.trade_only_high_volume,
            min_24h_volume=self.config.risk.min_24h_volume,
            whitelist=self.config.risk.whitelist,
            blacklist=self.config.risk.blacklist,
            kill_switch_enabled=self.config.risk.kill_switch_enabled,
        ))
        
        # Initialize execution engine
        self.execution_engine = ExecutionEngine(
            client=self.client,
            risk_manager=self.risk_manager,
            portfolio=self.portfolio,
            config=ExecutionConfig(
                slippage_tolerance=self.config.trading.slippage_tolerance,
                order_timeout_seconds=self.config.trading.order_timeout_seconds,
                dry_run=self.config.is_dry_run,
            ),
        )
        await self.execution_engine.start()
        
        # Initialize arb engine
        self.arb_engine = ArbEngine(ArbConfig(
            min_edge=self.config.trading.min_edge,
            bundle_arb_enabled=self.config.trading.bundle_arb_enabled,
            min_spread=self.config.trading.min_spread,
            mm_enabled=self.config.trading.mm_enabled,
            tick_size=self.config.trading.tick_size,
            default_order_size=self.config.trading.default_order_size,
            min_order_size=self.config.trading.min_order_size,
            max_order_size=self.config.trading.max_order_size,
        ))
        
        # Initialize data feed
        market_ids = self.config.trading.markets.copy()
        self.data_feed = DataFeed(
            client=self.client,
            market_ids=market_ids,
            position_refresh_interval=5.0,
            on_update=self._on_market_update,
            config=self.config,
        )
        await self.data_feed.start()
        
        # Initialize dashboard integration
        self.dashboard_integration = DashboardIntegration(
            data_feed=self.data_feed,
            arb_engine=self.arb_engine,
            execution_engine=self.execution_engine,
            risk_manager=self.risk_manager,
            portfolio=self.portfolio,
            mode="dry_run" if self.config.is_dry_run else "live",
        )
        await self.dashboard_integration.start()
        
        # Start fill simulation for dry run
        if self.config.is_dry_run and self.config.mode.simulate_fills:
            asyncio.create_task(self._simulate_fills())
        
        # Start the web server
        await self._start_server()
        
        logger.info("Bot and dashboard started successfully!")
        logger.info(f"Open http://{self.host}:{self.port} in your browser and sign in")
    
    async def _start_server(self) -> None:
        """Start the uvicorn server."""
        loopback = self.host in ("127.0.0.1", "localhost", "::1")
        if not loopback and not self.config.server.cookie_secure:
            logger.warning(
                "Dashboard is bound to %s with server.cookie_secure=false: session "
                "cookies would travel over plain HTTP. Put an HTTPS reverse proxy "
                "in front and set cookie_secure: true (see docs/deploy.md).", self.host)
        app = create_app(self.config, db=self.db)
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())
    
    def _on_market_update(self, market_id: str, market_state) -> None:
        """Handle market updates."""
        if not self._running or self.config.mode.paused:
            return
        
        # Check risk limits
        if not self.risk_manager.within_global_limits():
            return
        
        # Analyze for opportunities
        signals = self.arb_engine.analyze(market_state)
        
        for signal in signals:
            # Add to dashboard
            if signal.opportunity:
                self.dashboard_integration.add_opportunity(
                    opportunity_type=signal.opportunity.opportunity_type.value,
                    market_id=signal.market_id,
                    edge=signal.opportunity.edge,
                    suggested_size=signal.opportunity.suggested_size,
                )
            
            self.dashboard_integration.add_signal(
                action=signal.action,
                market_id=signal.market_id,
            )
            
            # Submit to execution
            asyncio.create_task(self.execution_engine.submit_signal(signal))
    
    async def _simulate_fills(self) -> None:
        """Simulate order fills in dry run mode."""
        import random
        
        while self._running:
            try:
                await asyncio.sleep(2.0)
                if self.config.mode.paused:
                    continue
                
                orders = self.execution_engine.get_open_orders()
                for order in orders:
                    if random.random() < self.config.mode.fill_probability:
                        trade = self.client.simulate_fill(order.order_id)
                        if trade:
                            self.execution_engine.handle_fill(trade)
                            self.dashboard_integration.add_trade(
                                side=trade.side.value,
                                price=trade.price,
                                size=trade.size,
                                market_id=trade.market_id,
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fill simulation error: {e}")
    
    async def _start_kalshi_monitoring(self) -> None:
        """Start monitoring Kalshi markets for cross-platform arbitrage."""
        if not self.kalshi_client:
            return
        
        logger.info("Starting Kalshi market monitoring...")
        
        # The client stays open for the whole run: the scanner fetches Kalshi
        # order books through it.
        await self.kalshi_client.__aenter__()
        self._kalshi_entered = True
        
        # Set up dashboard for loading state
        dashboard_state.cross_platform["enabled"] = True
        dashboard_state.cross_platform["matching_status"] = "loading"
        
        # Fetch Kalshi markets with progress updates
        logger.info("Fetching Kalshi markets...")
        
        def on_kalshi_progress(count):
            dashboard_state.cross_platform["kalshi_markets"] = count
        
        self._kalshi_markets = await self.kalshi_client.list_all_markets(
            status="open",
            max_markets=10000,
            on_progress=on_kalshi_progress,
        )
        logger.info(f"Loaded {len(self._kalshi_markets)} Kalshi markets")
        
        # Update dashboard state
        dashboard_state.cross_platform["kalshi_markets"] = len(self._kalshi_markets)
        
        # Wait for at least SOME Polymarket markets to load (start matching quickly!)
        logger.info("Waiting for Polymarket markets...")
        for i in range(30):  # Wait up to 30 seconds
            await asyncio.sleep(1)
            poly_count = len(self.data_feed._markets) if self.data_feed else 0
            
            # Update dashboard with current loading progress
            dashboard_state.cross_platform["polymarket_markets"] = poly_count
            
            # Start matching as soon as we have some markets from both platforms
            if poly_count >= 50:
                logger.info(f"Got {poly_count} Polymarket markets - starting matching!")
                break
                
            if i % 5 == 0:
                logger.info(f"Polymarket: {poly_count} markets loaded...")
        
        # Match markets between platforms (run in background so dashboard stays responsive)
        if self.data_feed and self._kalshi_markets:
            polymarket_markets = list(self.data_feed._markets.values())
            logger.info(f"Starting background matching: {len(polymarket_markets)} Polymarket x {len(self._kalshi_markets)} Kalshi")
            
            # Set initial status
            dashboard_state.cross_platform["matching_status"] = "starting"
            
            # Start matching as a background task (dashboard will show progress)
            self._background_tasks.append(
                asyncio.create_task(self._run_matching_background(polymarket_markets)))
    
    def _start_simulated_cross_platform(self) -> None:
        """Seed the pair store with synthetic pairs and serve synthetic books."""
        from core.simulation_pairs import DemoMarkets
        logger.info("Simulation mode: using the seeded demo pairs (no Kalshi/PredictIt calls)")
        demo = DemoMarkets()
        self.config.predictit.enabled = True  # the demo includes PredictIt pairs (in memory only)
        self.cross_platform_engine = CrossPlatformArbEngine(
            min_edge=self.config.trading.min_edge,
            min_match_similarity=self.config.mode.min_match_similarity,
            min_edge_provider=lambda: self.config.trading.min_edge,
            predictit_min_net_edge=self.config.predictit.min_net_edge,
        )
        self.market_matcher = self.cross_platform_engine.matcher
        self._setup_cross_platform_services(fetchers={
            "polymarket": demo.fetcher("polymarket"),
            "kalshi": demo.fetcher("kalshi"),
            "predictit": demo.fetcher("predictit"),
        })
        dashboard_state.cross_platform.update({
            "enabled": True, "matching_status": "complete", "matching_progress": 100,
            "kalshi_markets": 6, "polymarket_markets": 8, "simulated": True})
        pairs = demo.pairs()
        self.pair_store.add_many(pairs)
        dashboard_state.cross_platform["matched_pairs"] = len(pairs)
        self.ai.queue.enqueue_pending()
    
    def _setup_cross_platform_services(self, fetchers: dict = None) -> None:
        """Pair store, AI verifier queue and the scan loop."""
        from core.ai.service import build_ai_services
        
        dashboard_state.pair_store = self.pair_store
        with self.db.session() as s:
            self.pair_store.set_dismissed_keys(repo.dismissed_pair_keys(s))
        
        self.scanner = CrossPlatformScanner(
            self.cross_platform_engine, self.pair_store,
            fetchers=fetchers or {
                "polymarket": self._fetch_polymarket_book,
                "kalshi": self._fetch_kalshi_book,
                "predictit": self._fetch_predictit_book,
            },
            state=dashboard_state, db=self.db, config=self.config,
            emit=dashboard_state.emit,
            max_pairs=self.config.mode.scan_max_pairs_per_cycle,
        )
        self.ai = build_ai_services(
            self.config.ai, self.db, self.pair_store, dashboard_state.emit,
            on_verified=self.scanner.on_pair_verified,
        )
        self.scanner.analyst = self.ai.analyst
        dashboard_state.ai = self.ai
        dashboard_state.scanner = self.scanner
        async def on_predictit_toggled(enabled: bool) -> None:
            if enabled:
                self._ensure_predictit()
        dashboard_state.setting_hooks["predictit.enabled"] = on_predictit_toggled
        dashboard_state.setting_hooks["ai.enabled"] = (
            lambda enabled: self.ai.on_enabled_changed(enabled, self.scanner))
        self.ai.queue.pause_check = lambda: self.config.mode.paused
        self.market_matcher.pause_gate = self._pause_gate
        self.ai.queue.start()
        self._scan_task = asyncio.create_task(
            self.scanner.run(self.config.mode.scan_interval_s))
        logger.info(
            "Cross-platform gate: AI %s (provider=%s, model=%s)",
            "ON" if self.config.ai.enabled else "OFF",
            self.ai.provider.name, self.ai.provider.model)
        if self.config.ai.enabled and not self.ai.configured():
            logger.warning(
                "AI verification is ON but GEMINI_API_KEY is not set: no pair can be "
                "verified, so nothing will ever be marked actionable. Add the key as an "
                "environment variable, or turn AI verification off in Settings.")
    
    def _flush_pairs(self, inbox: PairInbox) -> int:
        """Move pairs found by the matching thread into the store and the verification queue."""
        pairs = inbox.drain()
        if not pairs:
            return 0
        new = self.pair_store.add_many(pairs)
        if new and self.ai is not None:
            self.ai.queue.enqueue_pending()
        dashboard_state.cross_platform["matched_pairs"] = len(self.pair_store.all())
        if new:
            logger.info("%d new pairs queued for verification (%d total)",
                        len(new), len(self.pair_store.all()))
        return len(new)
    
    def _pause_gate(self) -> None:
        """Block the matching worker thread while processing is paused."""
        import time
        while self.config.mode.paused and self._running:
            time.sleep(0.5)
    
    async def _fetch_polymarket_book(self, market_id: str):
        state = self.data_feed.get_market_state(market_id) if self.data_feed else None
        book = state.order_book if state else None
        if book is not None and book.best_ask_yes and book.best_bid_yes:
            return book
        # The live stream rotates through ~2000 markets, so this one may not have
        # been fetched yet: ask for its book directly instead of skipping the pair.
        try:
            return await self.client.get_orderbook(market_id)
        except Exception as e:
            logger.debug("On-demand Polymarket book failed for %s: %s", market_id, e)
            return book
    
    async def _fetch_predictit_book(self, contract_key: str):
        return await self.predictit.fetch_orderbook(contract_key) if self.predictit else None
    
    def _ensure_predictit(self) -> None:
        """Start the PredictIt poller if enabled and not already running."""
        if self.predictit is not None or not self.config.predictit.enabled \
                or self.cross_platform_engine is None or self.config.use_simulation:
            return
        self.predictit = build_predictit_client(self.config)
        if self.predictit is None:
            return
        logger.info("PredictIt enabled (read-only; data is licensed for non-commercial use)")
        self._background_tasks.append(asyncio.create_task(self._predictit_loop()))
    
    async def _predictit_loop(self) -> None:
        """Poll PredictIt, and match its contracts against Polymarket and Kalshi."""
        polls = 0
        while self._running:
            if self.config.mode.paused:
                await asyncio.sleep(2.0)
                continue
            try:
                markets = await self.predictit.get_markets()
                dashboard_state.cross_platform["predictit_markets"] = len(markets)
                # Match on the first successful poll, then every ~30 minutes for new contracts
                every = max(1, int(1800 / self.predictit.poll_interval_s))
                if markets and polls % every == 0:
                    await self._match_predictit()
                polls += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("PredictIt poll failed")
            await asyncio.sleep(self.predictit.poll_interval_s)
    
    async def _match_predictit(self) -> None:
        pi_refs = self.predictit.comparable_markets()
        if not pi_refs or self.data_feed is None:
            return
        sources = [[from_polymarket(m) for m in self.data_feed._markets.values() if m.active]]
        if self._kalshi_markets:
            sources.append([from_kalshi(k) for k in self._kalshi_markets if k.is_active])
        pairs = []
        for refs in sources:
            if refs:
                pairs.extend(await self._match_in_thread(refs, pi_refs))
        new_pairs = self.pair_store.add_many(pairs)
        if self.ai is not None:
            self.ai.queue.enqueue_pending()
        dashboard_state.cross_platform["matched_pairs"] = len(self.pair_store.all())
        logger.info("PredictIt matching: %d pairs, %d new", len(pairs), len(new_pairs))
    
    async def _match_in_thread(self, refs_a: list, refs_b: list) -> list:
        """Run the (CPU-bound) matcher off the event loop."""
        loop = asyncio.get_running_loop()
        
        def run():
            inner = asyncio.new_event_loop()
            try:
                return inner.run_until_complete(self.market_matcher.match_refs(refs_a, refs_b))
            finally:
                inner.close()
        return await loop.run_in_executor(None, run)
    
    async def _fetch_kalshi_book(self, ticker: str):
        if not self.kalshi_client or not self._kalshi_entered:
            return None
        return await self.kalshi_client.get_orderbook_unified(ticker)
    
    async def _run_matching_background(self, polymarket_markets: list) -> None:
        """Run market matching in a thread pool so dashboard stays fully responsive."""
        import concurrent.futures
        
        try:
            dashboard_state.cross_platform["matching_status"] = "matching"
            total = len(polymarket_markets) * len(self._kalshi_markets)
            dashboard_state.cross_platform["matching_total"] = total
            
            # Run matching in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            # Pairs go to verification and scanning as they are found, not after the whole run
            inbox = PairInbox()
            
            def run_matching_sync():
                """Synchronous matching that runs in thread."""
                import asyncio
                # Create new event loop for this thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                
                try:
                    def on_progress(checked, total, matches_found):
                        dashboard_state.cross_platform["matching_total"] = total
                        dashboard_state.cross_platform["matching_checked"] = checked
                        dashboard_state.cross_platform["matching_progress"] = int(checked / total * 100) if total > 0 else 0
                        dashboard_state.cross_platform["matched_pairs"] = matches_found
                        
                        # Update display data incrementally (show latest matches)
                        cached_pairs = self.market_matcher.get_cached_pairs()
                        if cached_pairs:
                            display_data = []
                            for pair in cached_pairs[-50:]:  # Show latest 50
                                display_data.append({
                                    "poly_question": pair.polymarket_question,
                                    "kalshi_title": pair.kalshi_title,
                                    "similarity": pair.similarity_score,
                                    "category": pair.category,
                                })
                            dashboard_state.cross_platform["matched_pairs_data"] = display_data
                    
                    result = new_loop.run_until_complete(
                        self.market_matcher.find_matches(
                            polymarket_markets,
                            self._kalshi_markets,
                            on_progress=on_progress,
                            on_match=inbox.put,
                        )
                    )
                    return result
                finally:
                    new_loop.close()
            
            async def flush_while_matching():
                while True:
                    await asyncio.sleep(3.0)
                    self._flush_pairs(inbox)
            
            flusher = asyncio.create_task(flush_while_matching())
            try:
                self._matched_pairs = await loop.run_in_executor(executor, run_matching_sync)
            finally:
                flusher.cancel()
                self._flush_pairs(inbox)
            
            dashboard_state.cross_platform["matching_status"] = "complete"
            dashboard_state.cross_platform["matching_progress"] = 100
            dashboard_state.cross_platform["matched_pairs"] = len(self._matched_pairs)
            
            logger.info(f"✓ Matching complete! Found {len(self._matched_pairs)} pairs")
            
            # Hand the proposed pairs to the verification gate
            new_pairs = self.pair_store.add_many(self._matched_pairs)
            if self.ai is not None:
                self.ai.queue.enqueue_pending()
            logger.info(f"{len(new_pairs)} new pairs queued for verification")
            
            # Prepare matched pairs data for dashboard display
            matched_pairs_display = []
            for pair in self._matched_pairs[:50]:
                matched_pairs_display.append({
                    "poly_question": pair.polymarket_question,
                    "kalshi_title": pair.kalshi_title,
                    "similarity": pair.similarity_score,
                    "category": pair.category,
                })
            
            dashboard_state.cross_platform["matched_pairs_data"] = matched_pairs_display
            
        except Exception as e:
            logger.error(f"Matching error: {e}")
            import traceback
            traceback.print_exc()
            dashboard_state.cross_platform["matching_status"] = "error"
    
    async def stop(self) -> None:
        """Stop everything gracefully."""
        logger.info("Shutting down...")
        self._running = False
        
        if self.dashboard_integration:
            await self.dashboard_integration.stop()
        
        if self.data_feed:
            await self.data_feed.stop()
        
        if self.execution_engine:
            await self.execution_engine.stop()
        
        if self.client:
            await self.client.disconnect()
        
        if self.scanner:
            self.scanner.stop()
        if self._scan_task:
            self._scan_task.cancel()
        if self.ai:
            await self.ai.queue.stop()
        for task in self._background_tasks:
            task.cancel()
        if self.kalshi_client and self._kalshi_entered:
            await self.kalshi_client.__aexit__(None, None, None)
        if self.predictit:
            await self.predictit.aclose()
        
        if self._server:
            self._server.should_exit = True
        
        # Final summary
        if self.portfolio:
            summary = self.portfolio.get_summary()
            logger.info("=" * 60)
            logger.info("Final Summary")
            logger.info("=" * 60)
            logger.info(f"Total PnL: ${summary['pnl']['total_pnl']:.2f}")
            logger.info(f"Trades: {summary['total_trades']}")
            logger.info(f"Win Rate: {summary['win_rate']:.1%}")
        
        # Cross-platform summary
        if self.cross_platform_engine:
            cp_stats = self.cross_platform_engine.get_stats()
            logger.info(f"Cross-Platform Opportunities: {cp_stats['total_opportunities']}")
            logger.info(f"Matched Market Pairs: {cp_stats['matched_pairs']}")
        
        if self.db:
            self.db.dispose()
        
        logger.info("Shutdown complete")
    
    async def run_forever(self) -> None:
        """Run until interrupted."""
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass


async def main_async(args: argparse.Namespace) -> None:
    """Async main function."""
    # Load config
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)
    
    # Override mode
    if args.live:
        config.mode.trading_mode = "live"
    elif args.dry_run:
        config.mode.trading_mode = "dry_run"
    
    # --live is rejected by validation: live trading is disabled in this build
    try:
        validate_config(config)
    except Exception as e:
        logger.error(f"{e}")
        sys.exit(1)
    
    host = args.host or config.server.host
    port = args.port or config.server.port
    
    # Create and run bot with dashboard
    bot = TradingBotWithDashboard(config, host=host, port=port)
    
    # Handle shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()
    
    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass
    
    try:
        await bot.start()
        
        # Wait for shutdown
        await shutdown_event.wait()
        
    except KeyboardInterrupt:
        pass
    finally:
        await bot.stop()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket Arbitrage Bot with Live Dashboard"
    )
    
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Config file path"
    )
    
    parser.add_argument(
        "--host",
        default=None,
        help="Dashboard bind address (default: server.host, 127.0.0.1)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Dashboard port (default: server.port, 8000)"
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Rejected: live trading is disabled in this build"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Run in dry-run mode (default)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging"
    )
    
    args = parser.parse_args()
    
    load_dotenv()
    
    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(console_level=log_level)
    
    # Run
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nShutdown complete.")


if __name__ == "__main__":
    main()

