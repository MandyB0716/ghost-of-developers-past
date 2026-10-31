"use strict";
const picker = document.getElementById("file-picker");
const status = document.getElementById("source-status");
function showSource(source, first, last) {
  const card = document.getElementById("source-" + source);
  if (!card) return;
  document.querySelectorAll(".source-file").forEach(item => { item.hidden = item !== card; });
  document.querySelectorAll(".selected-line").forEach(item => item.classList.remove("selected-line"));
  picker.value = source;
  if (first) {
    for (let line = first; line <= last; line++) {
      document.getElementById("source-" + source + "-L" + line)?.classList.add("selected-line");
    }
    const target = document.getElementById("source-" + source + "-L" + first);
    target?.scrollIntoView({block: "center", inline: "nearest"});
    status.textContent = picker.selectedOptions[0].textContent + " · " + (first === last ? "Line " + first : "Lines " + first + "–" + last);
  } else {
    const scroll = card.closest(".source-scroll");
    if (scroll) { scroll.scrollTop = 0; scroll.scrollLeft = 0; }
    status.textContent = picker.selectedOptions[0].textContent + " · Whole file (no line range cited)";
  }
}
document.addEventListener("click", event => {
    const link = event.target.closest("a.citation");
    if (!link) return;
    event.preventDefault();
    showSource(link.dataset.source, Number(link.dataset.first), Number(link.dataset.last));
    history.replaceState(null, "", link.getAttribute("href"));
});
picker.addEventListener("change", () => showSource(picker.value));
