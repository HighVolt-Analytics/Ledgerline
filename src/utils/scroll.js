export function scrollToSection(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const top = el.getBoundingClientRect().top + window.pageYOffset - 88;
  window.scrollTo({ top, behavior: 'smooth' });
}
