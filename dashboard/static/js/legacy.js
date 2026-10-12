        let ws = null;
        let state = {};
        let reconnectAttempts = 0;
        
        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = () => {
                console.log('WebSocket connected');
                document.getElementById('connectionStatus').textContent = '🟢 Connected';
                document.getElementById('connectionStatus').className = 'connection-status connected';
                reconnectAttempts = 0;
            };
            
            ws.onclose = (ev) => {
                if (ev.code === 4401 || ev.code === 4403) {
                    window.location.href = '/login';
                    return;
                }
                console.log('WebSocket disconnected');
                document.getElementById('connectionStatus').textContent = '🔴 Disconnected';
                document.getElementById('connectionStatus').className = 'connection-status disconnected';
                setTimeout(reconnect, Math.min(1000 * Math.pow(2, reconnectAttempts), 30000));
                reconnectAttempts++;
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                
                if (msg.type === 'initial' || msg.type === 'update') {
                    state = msg.data || msg;
                    updateDashboard();
                } else if (msg.type === 'opportunity') {
                    addOpportunity(msg.data);
                } else if (msg.type === 'activity') {
                    addActivity(msg.data);
                }
            };
        }
        
        function reconnect() {
            if (ws && ws.readyState === WebSocket.OPEN) return;
            connect();
        }
        
        function updateDashboard() {
            // Status
            const statusDot = document.getElementById('statusDot');
            const statusText = document.getElementById('statusText');
            if (state.is_running) {
                statusDot.className = 'status-dot running';
                statusText.textContent = 'Running';
            } else {
                statusDot.className = 'status-dot stopped';
                statusText.textContent = 'Stopped';
            }
            
            // Mode
            const modeBadge = document.getElementById('modeBadge');
            if (state.mode === 'live') {
                modeBadge.className = 'mode-badge live';
                modeBadge.textContent = 'LIVE';
            } else {
                modeBadge.className = 'mode-badge dry-run';
                modeBadge.textContent = 'DRY RUN';
            }
            
            // Metrics
            updateMetrics();
            
            // Opportunities
            updateOpportunities();
            
            // Activity
            updateActivity();
            
            // Risk
            updateRisk();
            
            // Timing
            updateTiming();
            
            // Operational
            updateOperational();
            
            // Cross-Platform
            updateCrossPlatform();
            
            // Markets
            updateMarkets();
        }
        
        function updateMetrics() {
            const portfolio = state.portfolio || {};
            const pnl = portfolio.pnl || {};
            const stats = state.stats || {};
            
            const totalPnl = pnl.total_pnl || 0;
            const realizedPnl = pnl.realized_pnl || 0;
            const exposure = portfolio.total_exposure || 0;
            const winRate = (portfolio.win_rate || 0) * 100;
            
            document.getElementById('totalPnl').textContent = formatCurrency(totalPnl);
            document.getElementById('totalPnl').className = `metric-value ${totalPnl >= 0 ? 'positive' : 'negative'}`;
            
            document.getElementById('realizedPnl').textContent = formatCurrency(realizedPnl);
            document.getElementById('realizedPnl').className = `metric-value ${realizedPnl >= 0 ? 'positive' : 'negative'}`;
            
            document.getElementById('exposure').textContent = formatCurrency(exposure);
            document.getElementById('openOrders').textContent = (state.orders || []).length;
            document.getElementById('opportunityCount').textContent = (state.opportunities || []).length;
            document.getElementById('winRate').textContent = `${winRate.toFixed(1)}%`;
            document.getElementById('winRate').className = `metric-value ${winRate >= 50 ? 'positive' : winRate > 0 ? 'neutral' : 'negative'}`;
        }
        
        function updateOpportunities() {
            const list = document.getElementById('opportunityList');
            const opportunities = state.opportunities || [];
            
            if (opportunities.length === 0) {
                list.innerHTML = '<div class="empty-state"><div class="empty-icon">📊</div><div>Waiting for opportunities...</div></div>';
                return;
            }
            
            const recent = opportunities.slice(-20).reverse();
            list.innerHTML = recent.map(opp => {
                const typeClass = opp.type?.includes('bundle') ? 
                    (opp.type.includes('long') ? 'bundle-long' : 'bundle-short') : 'mm';
                const typeLabel = opp.type?.replace('_', ' ').toUpperCase() || 'UNKNOWN';
                
                return `
                    <div class="opportunity-item">
                        <span class="opportunity-type ${typeClass}">${typeLabel}</span>
                        <div class="opportunity-details">
                            <div class="opportunity-market">${opp.market_id || 'Unknown'}</div>
                            <span class="opportunity-edge">Edge: ${((opp.edge || 0) * 100).toFixed(2)}%</span>
                        </div>
                        <span class="opportunity-time">${formatTime(opp.timestamp)}</span>
                    </div>
                `;
            }).join('');
            
            document.getElementById('oppRefresh').textContent = `Last: ${formatTime(state.last_update)}`;
        }
        
        function updateActivity() {
            const list = document.getElementById('activityList');
            const signals = state.signals || [];
            const trades = state.trades || [];
            
            // Combine and sort by timestamp
            const activities = [
                ...signals.map(s => ({...s, activityType: 'signal'})),
                ...trades.map(t => ({...t, activityType: 'trade'}))
            ].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 30);
            
            if (activities.length === 0) {
                list.innerHTML = '<div class="empty-state"><div class="empty-icon">📝</div><div>No activity yet...</div></div>';
                return;
            }
            
            list.innerHTML = activities.map(act => {
                let icon = '📋';
                let iconClass = 'signal';
                let message = '';
                
                if (act.activityType === 'trade') {
                    icon = '✓';
                    iconClass = 'fill';
                    message = `${act.side} ${(act.size || 0).toFixed(2)} @ ${(act.price || 0).toFixed(4)}`;
                } else {
                    icon = '→';
                    iconClass = 'signal';
                    message = `${act.action || 'Signal'}: ${act.market_id || ''}`;
                }
                
                return `
                    <div class="activity-item">
                        <div class="activity-icon ${iconClass}">${icon}</div>
                        <div class="activity-content">
                            <div class="activity-message">${message}</div>
                            <div class="activity-time">${formatTime(act.timestamp)}</div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        function updateRisk() {
            const risk = state.risk || {};
            
            const exposure = risk.global_exposure || 0;
            const maxExposure = risk.max_global_exposure || 5000;
            const exposurePct = (exposure / maxExposure) * 100;
            
            document.getElementById('riskExposure').textContent = `$${exposure.toFixed(0)} / $${maxExposure.toLocaleString()}`;
            document.getElementById('exposureBar').style.width = `${Math.min(exposurePct, 100)}%`;
            document.getElementById('exposureBar').className = `risk-bar-fill ${exposurePct < 60 ? 'safe' : exposurePct < 80 ? 'warning' : 'danger'}`;
            
            const dailyPnl = risk.daily_pnl || 0;
            const maxLoss = risk.max_daily_loss || 500;
            const dailyPnlPct = Math.abs(Math.min(dailyPnl, 0)) / maxLoss * 100;
            
            document.getElementById('riskDailyPnl').textContent = `$${dailyPnl.toFixed(2)} / -$${maxLoss}`;
            document.getElementById('dailyPnlBar').style.width = `${Math.min(dailyPnlPct, 100)}%`;
            document.getElementById('dailyPnlBar').className = `risk-bar-fill ${dailyPnlPct < 50 ? 'safe' : dailyPnlPct < 80 ? 'warning' : 'danger'}`;
            
            const drawdown = (risk.current_drawdown_pct || 0);
            const maxDrawdown = (risk.max_drawdown_pct || 10);
            const drawdownPct = (drawdown / maxDrawdown) * 100;
            
            document.getElementById('riskDrawdown').textContent = `${drawdown.toFixed(1)}% / ${maxDrawdown}%`;
            document.getElementById('drawdownBar').style.width = `${Math.min(drawdownPct, 100)}%`;
            document.getElementById('drawdownBar').className = `risk-bar-fill ${drawdownPct < 50 ? 'safe' : drawdownPct < 80 ? 'warning' : 'danger'}`;
            
            document.getElementById('killSwitch').style.display = risk.kill_switch_triggered ? 'block' : 'none';
        }
        
        function updateTiming() {
            const timing = state.timing || {};
            
            // Update count
            document.getElementById('timingCount').textContent = `${timing.total_tracked || 0} tracked`;
            
            // Update main stats
            const avgDuration = timing.avg_duration_ms;
            if (avgDuration !== undefined && avgDuration !== null) {
                document.getElementById('avgDuration').textContent = formatDuration(avgDuration);
                document.getElementById('avgDuration').className = `timing-stat-value ${getDurationClass(avgDuration)}`;
            }
            
            const minDuration = timing.min_duration_ms;
            if (minDuration !== undefined && minDuration !== null) {
                document.getElementById('minDuration').textContent = formatDuration(minDuration);
                document.getElementById('minDuration').className = `timing-stat-value ${getDurationClass(minDuration)}`;
            }
            
            const maxDuration = timing.max_duration_ms;
            if (maxDuration !== undefined && maxDuration !== null) {
                document.getElementById('maxDuration').textContent = formatDuration(maxDuration);
                document.getElementById('maxDuration').className = `timing-stat-value ${getDurationClass(maxDuration)}`;
            }
            
            document.getElementById('activeOpps').textContent = timing.active_opportunities || 0;
            
            // Update buckets
            document.getElementById('under100ms').textContent = timing.under_100ms || 0;
            document.getElementById('under500ms').textContent = timing.under_500ms || 0;
            document.getElementById('under1s').textContent = timing.under_1s || 0;
            document.getElementById('over1s').textContent = timing.over_1s || 0;
            
            // Update recent timings
            const recentList = document.getElementById('recentTimings');
            const recent = timing.recent_durations || [];
            
            if (recent.length === 0) {
                recentList.innerHTML = '<div class="u20">Waiting for opportunity data...</div>';
                return;
            }
            
            recentList.innerHTML = recent.slice().reverse().map(item => {
                const durationClass = getDurationClass(item.duration_ms);
                const typeLabel = item.type?.replace('_', ' ') || 'unknown';
                const executedBadge = item.executed ? '<span class="u21">✓</span>' : '';
                
                return `
                    <div class="timing-recent-item">
                        <span>${typeLabel} ${executedBadge}</span>
                        <span class="timing-duration ${durationClass}">${formatDuration(item.duration_ms)}</span>
                    </div>
                `;
            }).join('');
        }
        
        function formatDuration(ms) {
            if (ms === undefined || ms === null) return '--';
            if (ms < 1000) return `${Math.round(ms)}ms`;
            return `${(ms / 1000).toFixed(1)}s`;
        }
        
        function getDurationClass(ms) {
            if (ms < 200) return 'fast';
            if (ms < 1000) return 'medium';
            return 'slow';
        }
        
        let lastUpdateCount = 0;
        let lastUpdateTime = Date.now();
        
        function updateOperational() {
            const op = state.operational || {};
            const cp = state.cross_platform || {};
            
            // Show combined market count (Polymarket + Kalshi)
            const polyCount = cp.polymarket_markets || 0;
            const kalshiCount = cp.kalshi_markets || 0;
            const totalCombined = polyCount + kalshiCount;
            
            // Update stats - show combined if cross-platform is enabled
            const totalEl = document.getElementById('totalMarkets');
            if (cp.enabled && totalCombined > 0) {
                totalEl.innerHTML = `<span class="u22">${polyCount.toLocaleString()}</span> + <span class="u23">${kalshiCount.toLocaleString()}</span>`;
            } else {
                totalEl.textContent = op.total_markets || 0;
            }
            document.getElementById('marketsWithData').textContent = op.markets_with_orderbooks || 0;
            document.getElementById('marketsWithPrices').textContent = op.markets_with_prices || 0;
            document.getElementById('orderbookUpdates').textContent = formatNumber(op.orderbook_updates || 0);
            
            // Calculate updates per minute
            const now = Date.now();
            const timeDiff = (now - lastUpdateTime) / 1000; // seconds
            const updateDiff = (op.orderbook_updates || 0) - lastUpdateCount;
            
            if (timeDiff > 0 && lastUpdateCount > 0) {
                const updatesPerMin = Math.round((updateDiff / timeDiff) * 60);
                document.getElementById('updatesPerMin').textContent = updatesPerMin;
            }
            
            lastUpdateCount = op.orderbook_updates || 0;
            lastUpdateTime = now;
            
            // Estimate cycle time (time to check all markets)
            const totalMarkets = op.total_markets || 1;
            const updatesPerSec = (op.orderbook_updates || 0) / Math.max(state.uptime_seconds || 1, 1);
            if (updatesPerSec > 0) {
                const cycleSeconds = totalMarkets / updatesPerSec;
                document.getElementById('cycleTime').textContent = formatCycleTime(cycleSeconds);
            }
            
            // Stream status
            const statusEl = document.getElementById('streamStatus');
            if (op.is_streaming) {
                statusEl.textContent = '● Streaming';
                statusEl.style.color = 'var(--accent-green)';
            } else {
                statusEl.textContent = '○ Stopped';
                statusEl.style.color = 'var(--accent-red)';
            }
            
            // Uptime
            if (state.uptime_seconds) {
                document.getElementById('uptime').textContent = formatUptime(state.uptime_seconds);
            }
        }
        
        function formatNumber(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
            return num.toString();
        }
        
        function formatCycleTime(seconds) {
            if (seconds < 60) return Math.round(seconds) + 's';
            if (seconds < 3600) return Math.round(seconds / 60) + 'm';
            return (seconds / 3600).toFixed(1) + 'h';
        }
        
        function formatUptime(seconds) {
            const hrs = Math.floor(seconds / 3600);
            const mins = Math.floor((seconds % 3600) / 60);
            const secs = Math.floor(seconds % 60);
            return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }
        
        function updateCrossPlatform() {
            const cp = state.cross_platform || {};
            
            // Update status badge
            const statusEl = document.getElementById('crossPlatformStatus');
            if (cp.enabled) {
                statusEl.textContent = 'ACTIVE';
                statusEl.style.background = 'linear-gradient(135deg, #00ff88, #00cc66)';
            } else {
                statusEl.textContent = 'DISABLED';
                statusEl.style.background = 'linear-gradient(135deg, #666, #444)';
            }
            
            // Update stats
            const polyCount = cp.polymarket_markets || 0;
            const kalshiCount = cp.kalshi_markets || 0;
            const matchedCount = cp.matched_pairs || 0;
            const kalshiObs = cp.kalshi_orderbooks || 0;
            
            document.getElementById('polymarketMarkets').textContent = polyCount.toLocaleString();
            document.getElementById('kalshiMarkets').textContent = kalshiCount.toLocaleString();
            document.getElementById('matchedPairs').textContent = matchedCount;
            const kalshiObsEl = document.getElementById('kalshiOrderbooks');
            if (kalshiObsEl) kalshiObsEl.textContent = kalshiObs;
            
            // Update status indicators with loading animation
            const polyStatus = document.getElementById('polymarketStatus');
            const kalshiStatus = document.getElementById('kalshiStatus');
            
            // Polymarket status
            if (polyCount >= 5000) {
                polyStatus.textContent = '✓ Loaded';
                polyStatus.className = 'platform-stat-status ready';
            } else if (polyCount > 0) {
                polyStatus.textContent = `⏳ ${polyCount.toLocaleString()}...`;
                polyStatus.className = 'platform-stat-status loading';
            } else {
                polyStatus.textContent = '⏳ Loading...';
                polyStatus.className = 'platform-stat-status loading';
            }
            
            // Kalshi status
            if (kalshiCount >= 5000) {
                kalshiStatus.textContent = '✓ Loaded';
                kalshiStatus.className = 'platform-stat-status ready';
            } else if (kalshiCount > 0) {
                kalshiStatus.textContent = `⏳ ${kalshiCount.toLocaleString()}...`;
                kalshiStatus.className = 'platform-stat-status loading';
            } else {
                kalshiStatus.textContent = '⏳ Loading...';
                kalshiStatus.className = 'platform-stat-status loading';
            }
            
            const matchStatus = document.getElementById('matchingStatus');
            const kalshiObStatus = document.getElementById('kalshiObStatus');
            
            const matchingStatus = cp.matching_status || 'idle';
            const matchingProgress = cp.matching_progress || 0;
            const matchingChecked = cp.matching_checked || 0;
            const matchingTotal = cp.matching_total || 0;
            
            // Update progress bar
            const progressContainer = document.getElementById('matchingProgressContainer');
            const progressBar = document.getElementById('matchingProgressBar');
            const progressText = document.getElementById('matchingProgressText');
            const matchingStatsEl = document.getElementById('matchingStats');
            
            if (matchingStatus === 'matching' || matchingStatus === 'starting') {
                progressContainer.style.display = 'block';
                progressBar.style.width = `${matchingProgress}%`;
                progressText.textContent = `${matchingProgress}%`;
                matchingStatsEl.textContent = `Checked: ${matchingChecked.toLocaleString()} / ${matchingTotal.toLocaleString()} | Found: ${matchedCount} matches`;
                matchStatus.textContent = `🔍 ${matchingProgress}%`;
                matchStatus.className = 'platform-stat-status scanning';
            } else if (matchingStatus === 'complete') {
                progressContainer.style.display = 'none';
                matchStatus.textContent = `✓ ${matchedCount} pairs`;
                matchStatus.className = 'platform-stat-status ready';
            } else if (polyCount > 0 && kalshiCount > 0) {
                progressContainer.style.display = 'none';
                matchStatus.textContent = '⏳ Starting...';
                matchStatus.className = 'platform-stat-status loading';
            } else {
                progressContainer.style.display = 'none';
                matchStatus.textContent = 'Waiting...';
                matchStatus.className = 'platform-stat-status';
            }
            
            if (kalshiObs > 0) {
                kalshiObStatus.textContent = `${kalshiObs} fetched`;
                kalshiObStatus.className = 'platform-stat-status ready';
            } else if (matchedCount > 0) {
                kalshiObStatus.textContent = '⏳ Fetching...';
                kalshiObStatus.className = 'platform-stat-status loading';
            }
            
            const crossOpps = cp.cross_opportunities || [];
            const matchedPairsData = cp.matched_pairs_data || [];
            document.getElementById('crossOpportunities').textContent = crossOpps.length;
            
            // 🔥 Update Live Opportunities Feed
            updateOpportunitiesFeed(state, cp, matchedPairsData);
            
            // Update arb status
            const arbStatus = document.getElementById('arbStatus');
            if (crossOpps.length > 0) {
                arbStatus.textContent = `🎯 ${crossOpps.length} found!`;
                arbStatus.className = 'platform-stat-status ready';
            } else if (matchedCount > 0) {
                arbStatus.textContent = '🔍 Scanning...';
                arbStatus.className = 'platform-stat-status scanning';
            } else {
                arbStatus.textContent = 'Waiting...';
                arbStatus.className = 'platform-stat-status';
            }
            
            // Update matched pairs grid
            const grid = document.getElementById('matchedPairsGrid');
            if (!cp.enabled) {
                grid.innerHTML = '<div class="u24"><div class="u25">⏸️</div><div>Cross-platform mode disabled</div></div>';
                return;
            }
            
            if (matchedPairsData.length === 0 && crossOpps.length === 0) {
                const polyCount = cp.polymarket_markets || 0;
                const kalshiCount = cp.kalshi_markets || 0;
                grid.innerHTML = `<div class="u24">
                    <div class="u25">🔍</div>
                    <div>Scanning ${polyCount.toLocaleString()} Polymarket & ${kalshiCount.toLocaleString()} Kalshi markets...</div>
                    <div class="u26">Looking for matching NFL, NBA, Politics, Crypto predictions</div>
                </div>`;
                return;
            }
            
            // Render matched pairs as cards (show opportunities first, then other pairs)
            const allPairs = [...crossOpps.map(o => ({...o, hasArb: true})), ...matchedPairsData.slice(0, 20)];
            
            grid.innerHTML = allPairs.slice(0, 12).map((pair, idx) => {
                const hasArb = pair.hasArb || false;
                const edgePct = ((pair.edge_pct || 0) * 100);
                const category = detectCategory(pair.poly_question || pair.market_pair || '');
                
                return `
                    <div class="pair-card ${hasArb ? 'has-arb' : ''}">
                        <div class="pair-header">
                            <span class="pair-sport-badge">${category}</span>
                            ${hasArb ? '<span class="pair-arb-badge">⚡ Arb Available</span>' : ''}
                        </div>
                        <div class="pair-title">${truncate(pair.poly_question || pair.kalshi_title || 'Market ' + (idx + 1), 60)}</div>
                        <div class="pair-platforms">
                            <div class="platform-box">
                                <div class="platform-name">
                                    <span class="dot polymarket"></span>
                                    <span>Polymarket</span>
                                </div>
                                <div class="platform-prices">
                                    <span class="yes">${formatPct(pair.poly_yes || pair.buy_price)}</span>
                                    <span class="divider">/</span>
                                    <span class="no">${formatPct(pair.poly_no || (1 - (pair.buy_price || 0.5)))}</span>
                                </div>
                            </div>
                            <div class="platform-box">
                                <div class="platform-name">
                                    <span class="dot kalshi"></span>
                                    <span>Kalshi</span>
                                </div>
                                <div class="platform-prices">
                                    <span class="yes">${formatPct(pair.kalshi_yes || pair.sell_price)}</span>
                                    <span class="divider">/</span>
                                    <span class="no">${formatPct(pair.kalshi_no || (1 - (pair.sell_price || 0.5)))}</span>
                                </div>
                            </div>
                        </div>
                        <div class="pair-footer">
                            <span>Similarity: ${((pair.similarity || 0.8) * 100).toFixed(0)}%</span>
                            <span class="pair-edge ${edgePct > 1 ? 'positive' : 'negative'}">
                                ${hasArb ? `Edge: +${edgePct.toFixed(1)}%` : 'No arb'}
                            </span>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        // 🔥 Live Opportunities Feed Renderer
        function updateOpportunitiesFeed(state, cp, matchedPairs) {
            const feed = document.getElementById('opportunitiesFeed');
            const noOpps = document.getElementById('noOpportunities');
            const oppCount = document.getElementById('oppCount');
            
            // Collect ALL opportunities: bundle arb, cross-platform, and potential matches
            let allOpportunities = [];
            
            // 1. Add Polymarket bundle arbitrage opportunities
            const bundleOpps = state.opportunities || [];
            bundleOpps.forEach(opp => {
                allOpportunities.push({
                    type: 'polymarket',
                    title: opp.market_question || 'Bundle Arbitrage',
                    category: detectCategory(opp.market_question || ''),
                    edge: opp.net_edge_pct || opp.edge_pct || 0,
                    platform1: { name: 'Polymarket', price: opp.yes_price || 0.5, action: 'BUY YES' },
                    platform2: { name: 'Polymarket', price: opp.no_price || 0.5, action: 'BUY NO' },
                    marketInfo: 'Bundle: YES + NO < 100%'
                });
            });
            
            // 2. Add cross-platform opportunities
            const crossOpps = cp.cross_opportunities || [];
            crossOpps.forEach(opp => {
                allOpportunities.push({
                    type: 'cross-platform',
                    title: opp.market_pair || opp.token || 'Cross-Platform Arb',
                    category: detectCategory(opp.market_pair || opp.token || ''),
                    edge: opp.edge_pct || 0,
                    platform1: { name: opp.buy_platform || 'Polymarket', price: opp.buy_price || 0, action: 'BUY' },
                    platform2: { name: opp.sell_platform || 'Kalshi', price: opp.sell_price || 0, action: 'SELL' },
                    marketInfo: `${opp.buy_platform} vs ${opp.sell_platform}`
                });
            });
            
            // 3. Add matched pairs as potential opportunities (show best matches)
            if (matchedPairs && matchedPairs.length > 0) {
                matchedPairs.slice(0, 20).forEach(pair => {
                    // Only show high similarity matches
                    if ((pair.similarity || 0) >= 0.6) {
                        allOpportunities.push({
                            type: 'matched',
                            title: pair.poly_question || pair.kalshi_title || 'Matched Market',
                            category: detectCategory(pair.poly_question || pair.kalshi_title || ''),
                            edge: 0, // No arb found yet
                            similarity: pair.similarity || 0,
                            platform1: { name: 'Polymarket', price: pair.poly_yes || 0, action: 'Market' },
                            platform2: { name: 'Kalshi', price: pair.kalshi_yes || 0, action: 'Market' },
                            marketInfo: `Match: ${((pair.similarity || 0) * 100).toFixed(0)}% similar`
                        });
                    }
                });
            }
            
            // Sort by edge (highest first)
            allOpportunities.sort((a, b) => (b.edge || 0) - (a.edge || 0));
            
            // Update count
            const arbCount = allOpportunities.filter(o => o.edge > 0).length;
            oppCount.textContent = arbCount > 0 ? `${arbCount} ARB found!` : `${allOpportunities.length} matches`;
            
            // If no opportunities, show scanning message
            if (allOpportunities.length === 0) {
                noOpps.style.display = 'block';
                return;
            }
            
            noOpps.style.display = 'none';
            
            // Render opportunity cards
            const cardsHTML = allOpportunities.slice(0, 15).map(opp => {
                const edgePct = (opp.edge * 100).toFixed(2);
                const hasArb = opp.edge > 0;
                const cardClass = opp.type === 'cross-platform' ? 'cross-platform' : 
                                  opp.type === 'polymarket' ? 'polymarket' : 'kalshi';
                const badgeClass = getBadgeClass(opp.category);
                
                return `
                    <div class="opp-card ${cardClass}">
                        <div class="opp-header">
                            <div class="opp-category">
                                <span class="opp-badge ${badgeClass}">${opp.category}</span>
                                ${opp.type === 'cross-platform' ? '<span class="opp-badge cross">CROSS</span>' : ''}
                            </div>
                            ${hasArb ? 
                                `<div class="opp-edge">+${edgePct}%</div>` : 
                                (opp.similarity ? `<div class="u27">${(opp.similarity * 100).toFixed(0)}% match</div>` : '')
                            }
                        </div>
                        <div class="opp-title">${truncate(opp.title, 70)}</div>
                        <div class="opp-market-info">
                            <span class="u28">📊</span> ${opp.marketInfo}
                            ${hasArb ? '<span class="u29">● Active</span>' : ''}
                        </div>
                        <div class="opp-platforms">
                            <div class="opp-platform-row">
                                <div class="opp-platform-name">
                                    <span class="opp-platform-icon ${opp.platform1.name.toLowerCase().includes('poly') ? 'poly' : 'kalshi'}">
                                        ${opp.platform1.name.charAt(0)}
                                    </span>
                                    ${opp.platform1.name}
                                    ${hasArb ? '<span class="u30">↗</span>' : ''}
                                </div>
                                <div class="opp-platform-price ${hasArb ? 'buy' : ''}">${formatPct(opp.platform1.price)}</div>
                            </div>
                            <div class="opp-platform-row">
                                <div class="opp-platform-name">
                                    <span class="opp-platform-icon ${opp.platform2.name.toLowerCase().includes('kalshi') ? 'kalshi' : 'poly'}">
                                        ${opp.platform2.name.charAt(0)}
                                    </span>
                                    ${opp.platform2.name}
                                    ${hasArb ? '<span class="u31">↘</span>' : ''}
                                </div>
                                <div class="opp-platform-price ${hasArb ? 'sell' : ''}">${formatPct(opp.platform2.price)}</div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
            
            // Insert before the noOpportunities div
            feed.innerHTML = cardsHTML + '<div class="no-opportunities u32" id="noOpportunities"></div>';
        }
        
        function getBadgeClass(category) {
            const cat = category.toLowerCase();
            if (cat.includes('nfl') || cat.includes('football')) return 'nfl';
            if (cat.includes('nba') || cat.includes('basketball')) return 'nba';
            if (cat.includes('politic') || cat.includes('trump') || cat.includes('election')) return 'politics';
            if (cat.includes('crypto') || cat.includes('bitcoin')) return 'crypto';
            if (cat.includes('soccer') || cat.includes('premier') || cat.includes('league')) return 'soccer';
            return '';
        }
        
        function detectCategory(text) {
            const t = text.toLowerCase();
            if (t.includes('nfl') || t.includes('football') || t.includes('bears') || t.includes('chiefs') || t.includes('packers')) return 'NFL';
            if (t.includes('nba') || t.includes('basketball') || t.includes('lakers') || t.includes('celtics')) return 'NBA';
            if (t.includes('trump') || t.includes('biden') || t.includes('election') || t.includes('president')) return 'Politics';
            if (t.includes('bitcoin') || t.includes('btc') || t.includes('ethereum') || t.includes('crypto')) return 'Crypto';
            if (t.includes('fed') || t.includes('rate') || t.includes('inflation')) return 'Finance';
            return 'Other';
        }
        
        function formatPct(val) {
            if (val === undefined || val === null) return '??%';
            return (val * 100).toFixed(0) + '%';
        }
        
        function truncate(str, len) {
            if (!str) return '';
            return str.length > len ? str.substring(0, len) + '...' : str;
        }
        
        function updateMarkets() {
            const list = document.getElementById('marketList');
            const markets = state.markets || {};
            const marketIds = Object.keys(markets);
            const cp = state.cross_platform || {};
            
            // Show cross-platform matched pairs if available
            const matchedPairs = cp.matched_pairs_data || [];
            
            // If we have matched pairs from cross-platform, show those
            if (matchedPairs.length > 0) {
                list.innerHTML = matchedPairs.slice(0, 10).map((pair, idx) => {
                    const category = detectCategory(pair.poly_question || pair.kalshi_title || '');
                    const similarity = ((pair.similarity || 0) * 100).toFixed(0);
                    return `
                        <div class="market-item">
                            <div class="market-question">
                                <span class="opp-badge u33">${category}</span>
                                ${truncate(pair.poly_question || pair.kalshi_title || 'Market', 50)}
                            </div>
                            <div class="market-prices">
                                <span class="u34">P: ${pair.poly_yes ? formatPct(pair.poly_yes) : '--'}</span>
                                <span class="u35">K: ${pair.kalshi_yes ? formatPct(pair.kalshi_yes) : '--'}</span>
                                <span class="u36">${similarity}% match</span>
                            </div>
                        </div>
                    `;
                }).join('');
                return;
            }
            
            // Show Polymarket markets if available
            if (marketIds.length === 0) {
                const polyCount = cp.polymarket_markets || 0;
                const kalshiCount = cp.kalshi_markets || 0;
                
                if (polyCount > 0 || kalshiCount > 0) {
                    list.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-icon">🔄</div>
                            <div>Loading orderbooks...</div>
                            <div class="u37">
                                ${polyCount.toLocaleString()} Polymarket + ${kalshiCount.toLocaleString()} Kalshi markets
                            </div>
                        </div>
                    `;
                } else {
                    list.innerHTML = '<div class="empty-state"><div class="empty-icon">📈</div><div>Loading markets...</div></div>';
                }
                return;
            }
            
            list.innerHTML = marketIds.slice(0, 10).map(id => {
                const m = markets[id];
                const bid = m.best_bid_yes || 0;
                const ask = m.best_ask_yes || 0;
                const spread = ask - bid;
                
                return `
                    <div class="market-item">
                        <span class="market-name">${m.question || id}</span>
                        <span class="market-price">${bid.toFixed(2)}/${ask.toFixed(2)}</span>
                        <span class="market-spread">${(spread * 100).toFixed(1)}c</span>
                    </div>
                `;
            }).join('');
        }
        
        function formatCurrency(value) {
            const sign = value >= 0 ? '' : '-';
            return `${sign}$${Math.abs(value).toFixed(2)}`;
        }
        
        function formatTime(timestamp) {
            if (!timestamp) return '';
            const date = new Date(timestamp);
            return date.toLocaleTimeString();
        }
        
        function addOpportunity(opp) {
            if (!state.opportunities) state.opportunities = [];
            state.opportunities.push(opp);
            updateOpportunities();
        }
        
        function addActivity(activity) {
            if (!state.signals) state.signals = [];
            state.signals.push(activity);
            updateActivity();
        }
        
        // Ping to keep connection alive
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'ping'}));
            }
        }, 25000);
        
        // Fetch initial state via REST as backup
        async function fetchState() {
            try {
                const response = await fetch('/api/state');
                if (response.status === 401) {
                    window.location.href = '/login';
                    return;
                }
                state = await response.json();
                updateDashboard();
            } catch (e) {
                console.error('Failed to fetch state:', e);
            }
        }
        
        // Initial load
        connect();
        fetchState();
        
        // Periodic refresh as backup
        setInterval(fetchState, 5000);
    
