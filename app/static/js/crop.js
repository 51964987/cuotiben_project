/* 照片框选裁剪：在编辑页拖选图形区域，随表单提交（base64 PNG）。 */
(function () {
  var canvas = document.getElementById('crop-canvas');
  var img = document.getElementById('photo-img');
  if (!canvas || !img) return;

  var ctx = canvas.getContext('2d');
  var sel = null, dragging = false, sx = 0, sy = 0;

  function init() {
    var maxW = Math.min(canvas.parentElement.clientWidth || 600, 600);
    var scale = maxW / img.naturalWidth;
    canvas.width = maxW;
    canvas.height = Math.round(img.naturalHeight * scale);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  }

  function pos(e) {
    var r = canvas.getBoundingClientRect();
    var t = e.touches ? e.touches[0] : e;
    return { x: (t.clientX - r.left) * canvas.width / r.width,
             y: (t.clientY - r.top) * canvas.height / r.height };
  }

  function start(e) {
    e.preventDefault();
    var p = pos(e);
    dragging = true; sx = p.x; sy = p.y; sel = { x: p.x, y: p.y, w: 0, h: 0 };
    draw();
  }
  function move(e) {
    if (!dragging) return;
    e.preventDefault();
    var p = pos(e);
    sel = { x: Math.min(sx, p.x), y: Math.min(sy, p.y),
            w: Math.abs(p.x - sx), h: Math.abs(p.y - sy) };
    draw();
  }
  function end() { dragging = false; }

  function draw() {
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    if (!sel || sel.w < 3) return;
    ctx.save();
    ctx.strokeStyle = '#2563eb';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(sel.x, sel.y, sel.w, sel.h);
    ctx.fillStyle = 'rgba(37, 99, 235, 0.12)';
    ctx.fillRect(sel.x, sel.y, sel.w, sel.h);
    ctx.restore();
  }

  canvas.addEventListener('mousedown', start);
  canvas.addEventListener('mousemove', move);
  window.addEventListener('mouseup', end);
  canvas.addEventListener('touchstart', start, { passive: false });
  canvas.addEventListener('touchmove', move, { passive: false });
  canvas.addEventListener('touchend', end);

  window.getCropData = function () {
    if (img.complete && !canvas.width) init();
    if (!sel || sel.w < 10 || sel.h < 10) return '';
    var scale = img.naturalWidth / canvas.width;
    var ox = Math.round(sel.x * scale), oy = Math.round(sel.y * scale);
    var ow = Math.round(sel.w * scale), oh = Math.round(sel.h * scale);
    var out = document.createElement('canvas');
    out.width = ow; out.height = oh;
    out.getContext('2d').drawImage(img, ox, oy, ow, oh, 0, 0, ow, oh);
    return out.toDataURL('image/png');
  };

  if (img.complete) init();
  else img.onload = init;
})();
