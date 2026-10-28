// Smart text placement: move the text to the calmest band of the picture.
// window.PLACEMENT (from the renderer) holds, per row of the image as the
// page shows it, how busy it is (edges and detail) and how bright it is.
(function () {
  const data = window.PLACEMENT;
  const body = document.body;
  if (data && data.motion) body.classList.add("motion");
  if (data && data.cover) body.classList.add("cover");
  if (!data || !data.busy || !data.busy.length) return;
  const column = document.querySelector(body.dataset.place);
  const text = document.querySelector(body.dataset.placeText);
  if (!column || !text) return;
  const rows = data.busy.length;
  const pageHeight = data.height;
  const rowOf = (y) => Math.min(rows - 1, Math.max(0, Math.floor((y / pageHeight) * rows)));
  const boxHeight = column.offsetHeight;
  // Hidden lines (video layers) still take their space, so every layer
  // measures the same block and lands in the same place.
  const parts = [...text.children].filter((el) => el.offsetHeight);
  const textHeight = parts.length
    ? parts[parts.length - 1].getBoundingClientRect().bottom - parts[0].getBoundingClientRect().top
    : text.offsetHeight;
  const minTop = Number(body.dataset.placeMin);
  const maxBottom = Number(body.dataset.placeMax);
  const pad = 40;  // keep a little calm space around the words
  let best = null;
  for (let top = minTop; top + textHeight <= maxBottom; top += 10) {
    let cost = 0;
    const first = rowOf(top - pad);
    const last = rowOf(top + textHeight + pad);
    for (let row = first; row <= last; row++) cost += data.busy[row];
    cost /= (last - first + 1);
    // A slight preference for the upper part, where people expect words.
    cost += 0.12 * ((top - minTop) / Math.max(1, maxBottom - minTop));
    if (!best || cost < best.cost) best = { cost, top };
  }
  if (!best) return;
  // Centre the column on the chosen band.
  const columnTop = best.top - (boxHeight - textHeight) / 2;
  column.style.top = `${Math.round(columnTop)}px`;
  const centre = best.top + textHeight / 2;
  body.style.setProperty("--glow-y", `${Math.round(centre)}px`);
  // Text colour follows the brightness behind the chosen band.
  if (data.lum && data.lum.length) {
    let sum = 0;
    const first = rowOf(best.top);
    const last = rowOf(best.top + textHeight);
    for (let row = first; row <= last; row++) sum += data.lum[row];
    const brightness = (sum / (last - first + 1)) * (data.factor || 1);
    const tone = brightness > data.light ? "light" : brightness > data.mid ? "mid" : "dark";
    body.classList.remove("tone-light", "tone-mid", "tone-dark");
    body.classList.add(`tone-${tone}`);
  }
})();
