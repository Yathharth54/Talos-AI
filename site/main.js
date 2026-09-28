// Talos landing page: small, dependency-free motion layer.
// Everything here is progressive: without JS the page shows its final state.

const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const GLYPHS = "ΛΣΔ01<>/#_+=*";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** Replace text with random glyphs that settle left to right into the real string. */
function scramble(el, duration = 700) {
  const final = el.textContent;
  if (still) return Promise.resolve();
  return new Promise((resolve) => {
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      const settled = Math.floor(p * final.length);
      let out = final.slice(0, settled);
      for (let i = settled; i < final.length; i++) {
        out += final[i] === " " ? " " : GLYPHS[(Math.random() * GLYPHS.length) | 0];
      }
      el.textContent = out;
      if (p < 1) requestAnimationFrame(tick);
      else { el.textContent = final; resolve(); }
    };
    requestAnimationFrame(tick);
  });
}

/* nav background once the hero scrolls away */
const nav = document.getElementById("nav");
const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 40);
onScroll();
window.addEventListener("scroll", onScroll, { passive: true });

/* hero wordmark decode */
const word = document.querySelector("[data-scramble]");
if (word) setTimeout(() => scramble(word, 900), 450);

/* terminals: type the command, then print each line */
async function playTerms(root) {
  root.classList.add("played");
  const terms = [...root.querySelectorAll(".term-body")];
  const caret = document.createElement("span");
  caret.className = "caret";
  caret.setAttribute("aria-hidden", "true");

  const prepared = terms.map((body) => {
    const typed = body.querySelector(".typed");
    const text = typed.textContent;
    const lines = [...body.querySelectorAll(".ln:not(.cmd)")];
    if (!still) {
      typed.textContent = "";
      lines.forEach((l) => l.classList.add("pending"));
    }
    return { typed, text, lines };
  });
  if (still) return;

  for (const { typed, text, lines } of prepared) {
    typed.after(caret);
    await wait(350);
    for (let i = 1; i <= text.length; i++) {
      typed.textContent = text.slice(0, i);
      await wait(24 + Math.random() * 28);
    }
    await wait(300);
    caret.remove();
    for (const line of lines) {
      line.classList.remove("pending");
      await wait(line.classList.contains("g") ? 380 : 220);
    }
    await wait(700);
  }
  const last = prepared[prepared.length - 1];
  last.lines[last.lines.length - 1].append(caret);
}

/* vault: count up and decode the signatures */
function countUp(el) {
  const target = Number(el.dataset.count);
  if (still) return;
  const start = performance.now();
  const tick = (now) => {
    const p = Math.min((now - start) / 1400, 1);
    el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function revealSigs(list) {
  [...list.children].forEach((li, i) => {
    setTimeout(() => {
      li.classList.add("on");
      scramble(li.querySelector("b"), 420);
    }, still ? 0 : i * 70);
  });
}

/* one observer drives every scroll-triggered reveal, once each */
const io = new IntersectionObserver((entries) => {
  for (const { isIntersecting, target } of entries) {
    if (!isIntersecting) continue;
    io.unobserve(target);
    target.classList.add("in");
    if ("terms" in target.dataset) playTerms(target);
    if ("count" in target.dataset) countUp(target);
    if ("sigs" in target.dataset) revealSigs(target);
  }
}, { threshold: 0.3 });

document.querySelectorAll("[data-reveal]").forEach((el) => io.observe(el));
