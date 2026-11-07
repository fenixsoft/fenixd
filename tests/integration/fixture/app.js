// 极简交互脚本：点击「打招呼」按钮在输出行追加问候。
(function () {
  'use strict';
  var btn = document.getElementById('greet-btn');
  var out = document.getElementById('greet-output');
  if (!btn || !out) return;
  var clicks = 0;
  btn.addEventListener('click', function () {
    clicks += 1;
    out.textContent = '你好，fenixd！第 ' + clicks + ' 次问候。';
  });
})();
