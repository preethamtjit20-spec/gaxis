// Failsafe: ensure send button works even if app.js module has issues
(function() {
  var input = document.getElementById('task-input');
  var btn = document.getElementById('send-btn');
  if (!input || !btn) return;

  function syncBtn() {
    btn.disabled = !input.value.trim();
  }

  input.addEventListener('input', syncBtn);
  input.addEventListener('keyup', syncBtn);
  input.addEventListener('paste', function() { setTimeout(syncBtn, 50); });

  // Remove HTML disabled attribute on load
  btn.removeAttribute('disabled');
})();
