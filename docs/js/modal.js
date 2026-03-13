function openModal(s) {
  document.getElementById('modal-headline').textContent = s.headline || '—';
  document.getElementById('modal-pub').textContent = s.publication || '';

  const link = document.getElementById('modal-link');
  link.href = s.link || '#';
  link.style.display = s.link ? '' : 'none';

  const tbody = document.getElementById('modal-body');
  tbody.innerHTML = '';
  s.appearances.forEach(a => {
    const rank = /^\d+$/.test(a.rank) ? `#${a.rank}` : (a.rank || '—');
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${fmtDate(a.run_time)}</td><td>${badge(a.section)}</td><td>${rank}</td>`;
    tbody.appendChild(tr);
  });

  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
