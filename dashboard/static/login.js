(function () {
  var form = document.getElementById('loginForm');
  var errorEl = document.getElementById('error');
  var submit = document.getElementById('submit');

  function showError(msg) { errorEl.textContent = msg; errorEl.hidden = false; }

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    errorEl.hidden = true;
    submit.disabled = true;
    fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        username: form.username.value,
        password: form.password.value
      })
    }).then(function (res) {
      if (res.status === 204) { window.location.href = '/'; return; }
      if (res.status === 429) {
        var wait = parseInt(res.headers.get('Retry-After') || '0', 10);
        showError('Too many attempts. Try again' + (wait ? ' in ' + Math.ceil(wait / 60) + ' min.' : ' later.'));
      } else {
        showError('Invalid username or password.');
      }
      form.password.value = '';
      submit.disabled = false;
    }).catch(function () {
      showError('Could not reach the server.');
      submit.disabled = false;
    });
  });
})();
