// The Battlefield picker (templates/_battlefield_picker.html): saves the choice in the session,
// previews the map the next fight will use, and tells the page with a 'battlefield-change' event
// on document (detail: {arena, map}: the choice, and the map it means for the selected encounter).
const Battlefield = (function() {
  let picker, select, saved = {arena: null, map: null};
  const drawings = {};

  function mode() {
    return picker.querySelector('input[name="battlefield-mode"]:checked').value;
  }

  function choice() {
    return {none: '', own: picker.dataset.encounterMap, map: select.value}[mode()];
  }

  function fetchDrawing(name) {
    if (!drawings[name]) {
      drawings[name] = fetch(`/api/arenas/${encodeURIComponent(name)}`).then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      });
    }
    return drawings[name];
  }

  function describe() {
    const preview = document.getElementById('battlefield-preview');
    const caption = document.getElementById('battlefield-caption');
    const legend = document.getElementById('battlefield-legend');
    const summary = document.getElementById('battlefield-summary');
    preview.innerHTML = '';
    legend.innerHTML = '';
    if (!saved.map) {
      summary.textContent = 'No map';
      preview.innerHTML = '<div class="p-3 small text-muted">No map: the fight is abstract, with everyone in reach.</div>';
      caption.textContent = '';
      return;
    }
    summary.textContent = saved.arena === picker.dataset.encounterMap ? `Encounter's map: ${saved.map}` : saved.map;
    caption.textContent = 'Loading map…';
    const name = saved.map;
    fetchDrawing(name).then(arena => {
      if (saved.map !== name) return;  // the choice changed while loading
      const {svg, used} = ArenaMap.draw(arena, {cell: 12, startZones: arena.start_zones});
      preview.appendChild(svg);
      const size = `${arena.width * 5} × ${arena.height * 5} ft`;
      const own = saved.arena === picker.dataset.encounterMap;
      caption.textContent = `${arena.name} (${size}). ${arena.description || ''}` +
        (own ? ' Pick a different pre-built encounter to see its map.' : '');
      ArenaMap.legend(legend, [['Party starts', 'rgba(37,99,235,0.35)'], ['Monsters start', 'rgba(220,38,38,0.35)']]
        .concat(Array.from(used.entries())));
    }).catch(err => {
      caption.textContent = `Couldn't load the map: ${err.message}`;
    });
  }

  function announce() {
    describe();
    document.dispatchEvent(new CustomEvent('battlefield-change', {detail: {...saved}}));
  }

  function save() {
    const error = document.getElementById('arena-error');
    error.classList.add('d-none');
    select.disabled = mode() !== 'map';
    return fetch('/encounter/arena', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({arena: choice()})
    })
    .then(response => response.json().then(body => {
      if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
      saved = {arena: body.arena, map: body.map};
      announce();
    }))
    .catch(err => {
      error.textContent = `Couldn't save the battlefield: ${err.message}`;
      error.classList.remove('d-none');
    });
  }

  // The selected encounter changed: with "each encounter's own map" the map may have too
  function refresh() {
    return fetch('/encounter/arena').then(r => r.json()).then(body => {
      saved = {arena: body.arena, map: body.map};
      announce();
    });
  }

  function init() {
    picker = document.getElementById('battlefield-picker');
    if (!picker) return;
    select = document.getElementById('arena-select');
    picker.querySelectorAll('input[name="battlefield-mode"]').forEach(input => input.addEventListener('change', save));
    select.addEventListener('change', save);
    // Start from the choice the page was rendered with; pages listen from their own DOMContentLoaded
    saved = {arena: picker.dataset.arena || null, map: picker.dataset.map || null};
    describe();
    setTimeout(announce, 0);
  }

  document.addEventListener('DOMContentLoaded', init);
  return {refresh, current: () => ({...saved})};
})();
