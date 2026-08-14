(() => {
  const body = document.body;
  const stage = document.querySelector("main");
  const slides = [...document.querySelectorAll(".slide")];
  const progress = document.querySelector(".deck-progress span");
  const currentLabel = document.querySelector(".deck-counter b");
  const totalLabel = document.querySelector(".deck-counter i");
  const prevButton = document.querySelector('[data-action="prev"]');
  const nextButton = document.querySelector('[data-action="next"]');
  const fullscreenButton = document.querySelector('[data-action="fullscreen"]');
  const reveals = new Map();
  let current = 0;

  body.classList.add("interactive-mode");
  totalLabel.textContent = slides.length;

  const setReveal = (slideIndex, itemIndex) => {
    const reveal = reveals.get(slideIndex);
    if (!reveal) return;
    reveal.focused = itemIndex >= 0 && itemIndex < reveal.items.length ? itemIndex : -1;
    reveal.items.forEach((item, index) => {
      const active = index === reveal.focused;
      item.classList.toggle("is-revealed", active);
      item.setAttribute("aria-pressed", active ? "true" : "false");
    });
  };

  slides.forEach((slide, slideIndex) => {
    slide.setAttribute("role", "group");
    slide.setAttribute("aria-roledescription", "幻灯片");
    const group = slide.querySelector("[data-reveal]");
    const items = group ? [...group.querySelectorAll("[data-reveal-item]")] : [];
    if (group && items.length) {
      group.classList.add("reveal-ready");
      reveals.set(slideIndex, { items, focused: -1 });
      items.forEach((item, itemIndex) => {
        item.classList.add("reveal-item");
        item.tabIndex = 0;
        item.setAttribute("role", "button");
        item.setAttribute("aria-pressed", "false");
        const toggle = (event) => {
          event.preventDefault();
          event.stopPropagation();
          const reveal = reveals.get(slideIndex);
          setReveal(slideIndex, reveal.focused === itemIndex ? -1 : itemIndex);
        };
        item.addEventListener("click", toggle);
        item.addEventListener("keydown", (event) => {
          if (event.key === "Enter") toggle(event);
        });
      });
    }
    slide.addEventListener("click", (event) => {
      if (!event.target.closest("a, button, input, textarea, select, [data-reveal-item]")) goTo(current + 1);
    });
  });

  const fitDeck = () => {
    const fullscreen = Boolean(document.fullscreenElement);
    const horizontalRoom = Math.max(320, window.innerWidth - (fullscreen ? 0 : 32));
    const verticalRoom = Math.max(200, window.innerHeight - (fullscreen ? 0 : 88));
    const scale = Math.min(horizontalRoom / 960, verticalRoom / 540, fullscreen ? Infinity : 1.25);
    body.classList.toggle("is-fullscreen", fullscreen);
    body.style.setProperty("--deck-scale", scale.toFixed(4));
  };

  function goTo(index) {
    current = Math.max(0, Math.min(slides.length - 1, index));
    reveals.forEach((_, slideIndex) => {
      if (slideIndex !== current) setReveal(slideIndex, -1);
    });
    slides.forEach((slide, slideIndex) => {
      slide.classList.toggle("is-before", slideIndex < current);
      slide.classList.toggle("is-active", slideIndex === current);
      slide.classList.toggle("is-after", slideIndex > current);
      slide.setAttribute("aria-hidden", slideIndex === current ? "false" : "true");
    });
    currentLabel.textContent = current + 1;
    progress.style.width = `${((current + 1) / slides.length) * 100}%`;
    prevButton.disabled = current === 0;
    nextButton.disabled = current === slides.length - 1;
    history.replaceState(null, "", `#slide-${current + 1}`);
  }

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (_) {
      // Some local file contexts disable the Fullscreen API.
    }
  };

  prevButton.addEventListener("click", () => goTo(current - 1));
  nextButton.addEventListener("click", () => goTo(current + 1));
  fullscreenButton.addEventListener("click", toggleFullscreen);

  window.addEventListener("keydown", (event) => {
    const reveal = reveals.get(current);
    const number = Number(event.key);
    if (reveal && Number.isInteger(number) && number >= 1 && number <= reveal.items.length) {
      event.preventDefault();
      setReveal(current, number - 1);
    } else if (reveal && ["0", "Escape"].includes(event.key)) {
      event.preventDefault();
      setReveal(current, -1);
    } else if (["ArrowRight", "PageDown", " "].includes(event.key)) {
      event.preventDefault();
      if (reveal && reveal.focused < reveal.items.length - 1) setReveal(current, reveal.focused + 1);
      else goTo(current + 1);
    } else if (["ArrowLeft", "PageUp"].includes(event.key)) {
      event.preventDefault();
      if (reveal && reveal.focused >= 0) setReveal(current, reveal.focused - 1);
      else goTo(current - 1);
    } else if (event.key === "Home") goTo(0);
    else if (event.key === "End") goTo(slides.length - 1);
    else if (event.key.toLowerCase() === "f") toggleFullscreen();
  });

  window.addEventListener("resize", fitDeck);
  document.addEventListener("fullscreenchange", fitDeck);
  window.addEventListener("hashchange", () => {
    const match = location.hash.match(/slide-(\d+)/);
    if (match) goTo(Number(match[1]) - 1);
  });

  const match = location.hash.match(/slide-(\d+)/);
  fitDeck();
  goTo(match ? Number(match[1]) - 1 : 0);
})();
