// Charts for the batch results and Findings pages, drawn as SVG. Each chart is a <figure class="viz">
// with a .viz-plot to draw in, and a server-rendered .viz-table showing the same numbers that its
// .viz-toggle button swaps in. Colors come from static/css/charts.css.
const Charts = (function() {
  const NS = 'http://www.w3.org/2000/svg';
  const FONT = '12px system-ui, -apple-system, "Segoe UI", sans-serif';

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
    if (parent) parent.appendChild(node);
    return node;
  }

  function color(role) {
    return getComputedStyle(document.documentElement).getPropertyValue(`--viz-${role}`).trim();
  }

  let canvas;
  function textWidth(text) {
    canvas = canvas || document.createElement('canvas');
    const context = canvas.getContext('2d');
    context.font = FONT;
    return context.measureText(text).width;
  }

  function text(parent, x, y, content, attrs) {
    const node = el('text', Object.assign({x, y}, attrs), parent);
    node.textContent = content;
    return node;
  }

  // Round tick values from 0 to at least max: [0, step, 2 step, ...], about four steps
  function ticks(max) {
    if (max <= 0) return [0, 1];
    const raw = max / 4;
    const power = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 5, 10].map(m => m * power).find(s => s >= raw);
    const top = Math.ceil(max / step) * step;
    const values = [];
    for (let v = 0; v <= top + step / 2; v += step) values.push(Math.round(v * 1e6) / 1e6);
    return values;
  }

  // Column with a 4px rounded top, square at the baseline
  function columnPath(x, y, w, h) {
    const r = Math.min(4, h, w / 2);
    return `M${x},${y + h}V${y + r}A${r},${r} 0 0 1 ${x + r},${y}H${x + w - r}` +
           `A${r},${r} 0 0 1 ${x + w},${y + r}V${y + h}Z`;
  }

  // Horizontal bar with a 4px rounded end, square at the baseline
  function barPath(x, y, w, h) {
    const r = Math.min(4, w, h / 2);
    return `M${x},${y}H${x + w - r}A${r},${r} 0 0 1 ${x + w},${y + r}V${y + h - r}` +
           `A${r},${r} 0 0 1 ${x + w - r},${y + h}H${x}Z`;
  }

  // The tooltip: lines of {value, text, key (a series color)}; every value is also in the table
  let tip;
  function showTip(target, lines, event) {
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'viz-tooltip';
      document.body.appendChild(tip);
    }
    tip.replaceChildren();
    lines.forEach(line => {
      const row = document.createElement('div');
      row.className = line.value ? 'tip-value' : 'tip-line';
      if (line.key) {
        const key = document.createElement('span');
        key.className = 'tip-key';
        key.style.background = line.key;
        row.appendChild(key);
      }
      row.appendChild(document.createTextNode(line.value || line.text));
      tip.appendChild(row);
    });
    tip.hidden = false;
    let x, y;
    if (event && event.clientX !== undefined) {
      x = event.clientX + 14;
      y = event.clientY + 14;
    } else {
      const box = target.getBoundingClientRect();
      x = box.right + 6;
      y = box.top;
    }
    x = Math.min(x, document.documentElement.clientWidth - tip.offsetWidth - 8);
    tip.style.left = `${x + window.scrollX}px`;
    tip.style.top = `${y + window.scrollY}px`;
  }

  function hideTip() {
    if (tip) tip.hidden = true;
  }

  // A group the pointer or keyboard can land on, showing lines in the tooltip
  function hoverable(group, lines, label) {
    group.setAttribute('tabindex', '0');
    group.setAttribute('role', 'img');
    group.setAttribute('aria-label', label);
    group.addEventListener('pointermove', event => { group.classList.add('hover'); showTip(group, lines, event); });
    group.addEventListener('pointerleave', () => { group.classList.remove('hover'); hideTip(); });
    group.addEventListener('focus', () => { group.classList.add('hover'); showTip(group, lines); });
    group.addEventListener('blur', () => { group.classList.remove('hover'); hideTip(); });
  }

  // Draw now and again when the plot's width changes
  function responsive(plot, draw) {
    let width = 0;
    const redraw = () => {
      if (plot.clientWidth === width || plot.closest('.d-none')) return;
      width = plot.clientWidth;
      plot.replaceChildren();
      draw(width);
    };
    redraw();
    new ResizeObserver(redraw).observe(plot);
  }

  // The figure's "Show table" button: the table carries every value the chart does
  function tableToggle(figure) {
    const button = figure.querySelector('.viz-toggle');
    const table = figure.querySelector('.viz-table');
    const plot = figure.querySelector('.viz-plot');
    if (!button || !table) return;
    button.addEventListener('click', () => {
      const showTable = table.classList.contains('d-none');
      table.classList.toggle('d-none', !showTable);
      plot.classList.toggle('d-none', showTable);
      button.textContent = showTable ? 'Show chart' : 'Show table';
      button.setAttribute('aria-pressed', String(showTable));
    });
  }

  // A column chart of counts: data is [{label, value}], one series. options: xTitle, describe(d)
  // giving the tooltip's lines for a column.
  function columns(figure, data, options) {
    tableToggle(figure);
    const plot = figure.querySelector('.viz-plot');
    responsive(plot, width => {
      const height = 220, m = {top: 20, right: 8, bottom: 40, left: 36};
      const w = width - m.left - m.right, h = height - m.top - m.bottom;
      const yTicks = ticks(Math.max(...data.map(d => d.value), 1));
      const yMax = yTicks[yTicks.length - 1];
      const y = v => m.top + h - (v / yMax) * h;
      const band = w / data.length;
      const barWidth = Math.min(24, Math.max(2, band - 4));
      const svg = el('svg', {width, height}, plot);

      yTicks.forEach(v => {
        el('line', {x1: m.left, x2: m.left + w, y1: y(v), y2: y(v), stroke: color(v ? 'grid' : 'axis'),
                    'stroke-width': 1}, svg);
        text(svg, m.left - 6, y(v) + 4, String(v), {class: 'tick', 'text-anchor': 'end'});
      });

      // Label every column the band has room for, otherwise every second, fifth...
      const widest = Math.max(...data.map(d => textWidth(d.label)));
      const every = [1, 2, 5, 10, 20, 50].find(k => band * k >= widest + 8) || data.length;
      const tallest = data.reduce((best, d) => (d.value > best.value ? d : best), data[0]);

      data.forEach((d, i) => {
        const cx = m.left + band * (i + 0.5);
        const group = el('g', {}, svg);
        el('rect', {class: 'hit', x: m.left + band * i, y: m.top, width: band, height: h, fill: 'transparent'}, group);
        if (d.value > 0) {
          el('path', {class: 'mark', d: columnPath(cx - barWidth / 2, y(d.value), barWidth, y(0) - y(d.value)),
                      fill: color('series-1')}, group);
        }
        if (i % every === 0) {
          text(svg, cx, m.top + h + 16, d.label, {class: 'tick', 'text-anchor': 'middle'});
        }
        const lines = options.describe(d);
        hoverable(group, lines, lines.map(l => l.value || l.text).join(', '));
      });
      // Only the tallest column gets its value written on it
      if (tallest && tallest.value > 0) {
        const i = data.indexOf(tallest);
        text(svg, m.left + band * (i + 0.5), y(tallest.value) - 6, String(tallest.value),
             {class: 'value-label', 'text-anchor': 'middle'});
      }
      text(svg, m.left + w / 2, height - 4, options.xTitle, {class: 'axis-title', 'text-anchor': 'middle'});
    });
  }

  // Horizontal bars, one per row of data [{label, value, side}], colored by side (series:
  // {side: {label, role}}). options: format(value), describe(d).
  function bars(figure, data, options) {
    tableToggle(figure);
    const plot = figure.querySelector('.viz-plot');
    responsive(plot, width => {
      const row = 28, thickness = 16;
      const labelWidth = Math.min(width * 0.4, Math.max(...data.map(d => textWidth(d.label))) + 12);
      const valueWidth = Math.max(...data.map(d => textWidth(options.format(d.value)))) + 8;
      const m = {top: 4, right: valueWidth, bottom: 4, left: labelWidth};
      const w = Math.max(10, width - m.left - m.right);
      const height = m.top + m.bottom + row * data.length;
      const max = Math.max(...data.map(d => d.value), 1);
      const svg = el('svg', {width, height}, plot);
      el('line', {x1: m.left, x2: m.left, y1: m.top, y2: height - m.bottom, stroke: color('axis'), 'stroke-width': 1}, svg);

      data.forEach((d, i) => {
        const top = m.top + row * i;
        const group = el('g', {}, svg);
        el('rect', {class: 'hit', x: 0, y: top, width, height: row, fill: 'transparent'}, group);
        const length = (d.value / max) * w;
        if (length > 0) {
          el('path', {class: 'mark', d: barPath(m.left, top + (row - thickness) / 2, length, thickness),
                      fill: color(options.series[d.side].role)}, group);
        }
        text(group, m.left - 8, top + row / 2 + 4, d.label, {class: 'tick', 'text-anchor': 'end'});
        text(group, m.left + length + 6, top + row / 2 + 4, options.format(d.value), {class: 'value-label'});
        const lines = options.describe(d, color(options.series[d.side].role));
        hoverable(group, lines, lines.map(l => l.value || l.text).join(', '));
      });
    });
  }

  // The Findings chart: each batch's party win rate (a dot) in the band of its DMG rating, and each
  // rating's fights together (a line, with its 95% confidence interval as a wash).
  // data: {ratings: [{key, label}], batches: [{rating, rate, ...}], pooled: [{rating, rate, low, high, runs}]}
  // options: describeBatch(b), describePooled(p), poolLabel(p).
  function dots(figure, data, options) {
    tableToggle(figure);
    const plot = figure.querySelector('.viz-plot');
    responsive(plot, width => {
      const height = 320, m = {top: 12, right: 8, bottom: 48, left: 60};
      const w = width - m.left - m.right, h = height - m.top - m.bottom;
      const y = v => m.top + h - (v / 100) * h;
      const band = w / data.ratings.length;
      const svg = el('svg', {width, height}, plot);

      [0, 25, 50, 75, 100].forEach(v => {
        el('line', {x1: m.left, x2: m.left + w, y1: y(v), y2: y(v), stroke: color(v ? 'grid' : 'axis'),
                    'stroke-width': 1}, svg);
        text(svg, m.left - 6, y(v) + 4, `${v}%`, {class: 'tick', 'text-anchor': 'end'});
      });
      el('text', {class: 'axis-title', 'text-anchor': 'middle',
                  transform: `translate(11,${m.top + h / 2}) rotate(-90)`}, svg).textContent = 'Party win rate';

      data.ratings.forEach((rating, i) => {
        const left = m.left + band * i, cx = left + band / 2;
        text(svg, cx, m.top + h + 18, rating.label, {class: 'tick', 'text-anchor': 'middle'});
        const pooled = data.pooled.find(p => p.rating === rating.key);
        if (pooled && pooled.runs) {
          text(svg, cx, m.top + h + 34, options.poolLabel(pooled), {class: 'tick', 'text-anchor': 'middle'});
          const span = Math.min(band * 0.8, 120);
          const group = el('g', {}, svg);
          el('rect', {class: 'mark', x: cx - span / 2, y: y(pooled.high), width: span,
                      height: Math.max(1, y(pooled.low) - y(pooled.high)), fill: color('wash'), rx: 4}, group);
          el('line', {class: 'mark', x1: cx - span / 2, x2: cx + span / 2, y1: y(pooled.rate), y2: y(pooled.rate),
                      stroke: color('ink-secondary'), 'stroke-width': 2, 'stroke-linecap': 'round'}, group);
          const lines = options.describePooled(pooled);
          hoverable(group, lines, lines.map(l => l.value || l.text).join(', '));
        }

        // The rating's batches spread across its band so they don't all sit on one line
        const own = data.batches.filter(b => b.rating === rating.key);
        const step = own.length > 1 ? Math.min(14, (band * 0.7) / (own.length - 1)) : 0;
        own.forEach((b, j) => {
          const x = cx + (j - (own.length - 1) / 2) * step;
          const group = el('g', {}, svg);
          el('circle', {class: 'hit', cx: x, cy: y(b.rate), r: 12, fill: 'transparent'}, group);
          el('circle', {class: 'mark', cx: x, cy: y(b.rate), r: 5, fill: color('series-1'),
                        stroke: color('surface'), 'stroke-width': 2}, group);
          const lines = options.describeBatch(b);
          hoverable(group, lines, lines.map(l => l.value || l.text).join(', '));
        });
      });
    });
  }

  return {columns, bars, dots};
})();
