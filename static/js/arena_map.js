// Drawing battle maps as SVG: the replay on the results page and the Battlefield preview.
const ArenaMap = (function() {
  const NS = 'http://www.w3.org/2000/svg';
  const SIDE_COLORS = {party: '#2563eb', monsters: '#dc2626'};

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
    if (parent) parent.appendChild(node);
    return node;
  }

  // [label, color] for a terrain square
  function terrainStyle(kind, impassable, difficult, cover) {
    if (kind === 'water' || kind === 'shallows') return ['Water', '#7fb2e5'];
    if (kind === 'lava') return ['Lava', '#e0663a'];
    if (kind === 'tree') return ['Trees', '#5d9a5d'];
    if (impassable && cover === 'total') return ['Wall', '#555'];
    if (impassable && cover !== 'none') return ['Boulder or statue', '#8d8d8d'];
    if (impassable) return ['Water', '#7fb2e5'];
    if (cover !== 'none') return ['Low obstacle (cover)', '#a47b4f'];
    return ['Difficult terrain', '#d9c999'];
  }

  // The map's ground, terrain and grid. Returns the svg, an el() helper and the terrain kinds used
  // (label -> color) for a legend. With startZones, each side's starting area is tinted.
  function draw(arena, {cell = 24, startZones = null} = {}) {
    const svg = el('svg', {viewBox: `0 0 ${arena.width * cell} ${arena.height * cell}`,
                           width: '100%', role: 'img', 'aria-label': `Battle map of ${arena.name}`});
    const defs = el('defs', {}, svg);
    const hatch = el('pattern', {id: 'difficult', width: 6, height: 6, patternUnits: 'userSpaceOnUse',
                                 patternTransform: 'rotate(45)'}, defs);
    el('line', {x1: 0, y1: 0, x2: 0, y2: 6, stroke: 'rgba(0,0,0,0.25)', 'stroke-width': 2}, hatch);
    el('rect', {x: 0, y: 0, width: arena.width * cell, height: arena.height * cell, fill: '#f6f3ea'}, svg);
    const used = new Map();
    Object.entries(startZones || {}).forEach(([side, squares]) => {
      squares.forEach(([x, y]) => el('rect', {x: x * cell, y: y * cell, width: cell, height: cell,
                                              fill: SIDE_COLORS[side] || '#999', 'fill-opacity': 0.18}, svg));
    });
    (arena.terrain || []).forEach(([x, y, kind, impassable, difficult, cover]) => {
      const [label, color] = terrainStyle(kind, impassable, difficult, cover);
      used.set(label, color);
      el('rect', {x: x * cell, y: y * cell, width: cell, height: cell, fill: color}, svg);
      if (difficult) el('rect', {x: x * cell, y: y * cell, width: cell, height: cell, fill: 'url(#difficult)'}, svg);
    });
    const grid = el('g', {stroke: 'rgba(0,0,0,0.08)', 'stroke-width': 1}, svg);
    for (let x = 0; x <= arena.width; x++) el('line', {x1: x * cell, y1: 0, x2: x * cell, y2: arena.height * cell}, grid);
    for (let y = 0; y <= arena.height; y++) el('line', {x1: 0, y1: y * cell, x2: arena.width * cell, y2: y * cell}, grid);
    return {svg, el, used};
  }

  // A legend of colored swatches: entries are [label, color, round]
  function legend(container, entries) {
    container.innerHTML = '';
    entries.forEach(([label, color, round]) => {
      const item = document.createElement('span');
      const swatch = document.createElement('span');
      swatch.style.cssText = `display:inline-block;width:12px;height:12px;margin-right:4px;vertical-align:-1px;` +
        `background:${color};border-radius:${round ? '50%' : '2px'};`;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(label));
      container.appendChild(item);
    });
  }

  return {draw, legend, terrainStyle, el, SIDE_COLORS};
})();
