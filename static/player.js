// GenMedia Pulse — Interactive Podcast Audio Player, Transcript Sync & Subscribe Modal
(function () {
  "use strict";

  const root = document.documentElement;
  const themeBtn = document.getElementById("theme-toggle-btn");
  const savedTheme = localStorage.getItem("genmedia_pulse_theme");
  if (savedTheme === "dark" || savedTheme === "light") {
    root.setAttribute("data-theme", savedTheme);
  }

  function syncThemeLabel() {
    if (!themeBtn) return;
    const isDark = root.getAttribute("data-theme") === "dark";
    themeBtn.textContent = isDark ? "Light Paper" : "Dark Room";
  }
  syncThemeLabel();

  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      localStorage.setItem("genmedia_pulse_theme", next);
      syncThemeLabel();
    });
  }

  // Lock horizontal touch drift/bounce on mobile (while allowing audio seek-slider drag)
  let touchStartX = 0;
  let touchStartY = 0;
  document.addEventListener(
    "touchstart",
    function (ev) {
      if (ev.touches.length !== 1) return;
      touchStartX = ev.touches[0].clientX;
      touchStartY = ev.touches[0].clientY;
    },
    { passive: true }
  );
  document.addEventListener(
    "touchmove",
    function (ev) {
      if (ev.touches.length !== 1) return;
      const target = ev.target;
      if (target && target.closest && target.closest("#player-seek-slider")) {
        return;
      }
      const dx = Math.abs(ev.touches[0].clientX - touchStartX);
      const dy = Math.abs(ev.touches[0].clientY - touchStartY);
      if (dx > 8 && dx > dy * 1.15) {
        ev.preventDefault();
      }
    },
    { passive: false }
  );

  // Segmented tabs: Written Digest vs. Two-Host Transcript
  const tabButtons = Array.from(document.querySelectorAll(".tab-btn"));
  const tabPanes = Array.from(document.querySelectorAll(".tab-pane"));

  function activateTab(targetId) {
    tabButtons.forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.target === targetId);
    });
    tabPanes.forEach(function (pane) {
      pane.classList.toggle("active", pane.id === targetId);
    });
  }

  tabButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      activateTab(btn.dataset.target);
    });
  });

  // Subscribe RSS Modal
  const modal = document.getElementById("subscribe-modal");
  const openModalBtn = document.getElementById("open-subscribe-btn");
  const closeModalBtn = document.getElementById("close-subscribe-btn");
  const copyRssBtn = document.getElementById("copy-rss-btn");
  const rssInput = document.getElementById("rss-feed-url-input");

  if (openModalBtn && modal) {
    openModalBtn.addEventListener("click", function () {
      modal.classList.add("open");
    });
  }
  if (closeModalBtn && modal) {
    closeModalBtn.addEventListener("click", function () {
      modal.classList.remove("open");
    });
  }
  if (modal) {
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) modal.classList.remove("open");
    });
  }
  if (copyRssBtn && rssInput) {
    copyRssBtn.addEventListener("click", function () {
      navigator.clipboard.writeText(rssInput.value).then(function () {
        const orig = copyRssBtn.textContent;
        copyRssBtn.textContent = "Copied!";
        setTimeout(function () {
          copyRssBtn.textContent = orig;
        }, 1800);
      });
    });
  }

  // Audio Player & Click-to-Seek Transcript Synchronization
  const audio = document.getElementById("podcast-audio-el");
  if (!audio) return;

  const heroPlayBtn = document.getElementById("hero-play-btn");
  const barPlayBtn = document.getElementById("player-play-btn");
  const back15Btn = document.getElementById("player-back-15-btn");
  const fwd15Btn = document.getElementById("player-fwd-15-btn");
  const speedBtn = document.getElementById("player-speed-btn");
  const seekSlider = document.getElementById("player-seek-slider");
  const curTimeEl = document.getElementById("player-current-time");
  const durTimeEl = document.getElementById("player-total-time");
  const liveSpeakerEl = document.getElementById("player-live-speaker");
  const turnCards = Array.from(document.querySelectorAll(".turn-card"));

  const speeds = [1.0, 1.25, 1.5, 1.75, 2.0, 0.85];
  let speedIdx = 0;

  function fmtTime(sec) {
    if (!isFinite(sec) || sec < 0) return "00:00";
    const total = Math.floor(sec);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }

  function syncPlayButtons() {
    const playing = !audio.paused;
    if (barPlayBtn) barPlayBtn.textContent = playing ? "Pause" : "Play";
    if (heroPlayBtn) {
      heroPlayBtn.textContent = playing ? "Pause Episode" : "Listen to 5-Min Briefing";
    }
  }

  function togglePlayback() {
    if (audio.paused) {
      audio.play().catch(function () {});
    } else {
      audio.pause();
    }
  }

  if (barPlayBtn) barPlayBtn.addEventListener("click", togglePlayback);
  if (heroPlayBtn) heroPlayBtn.addEventListener("click", togglePlayback);

  if (back15Btn) {
    back15Btn.addEventListener("click", function () {
      audio.currentTime = Math.max(0, (audio.currentTime || 0) - 15);
    });
  }
  if (fwd15Btn) {
    fwd15Btn.addEventListener("click", function () {
      const cap = isFinite(audio.duration) ? audio.duration : (audio.currentTime || 0) + 15;
      audio.currentTime = Math.min(cap, (audio.currentTime || 0) + 15);
    });
  }
  if (speedBtn) {
    speedBtn.addEventListener("click", function () {
      speedIdx = (speedIdx + 1) % speeds.length;
      audio.playbackRate = speeds[speedIdx];
      speedBtn.textContent = speeds[speedIdx].toFixed(2).replace(/\.00$/, ".0") + "x";
    });
  }

  audio.addEventListener("play", syncPlayButtons);
  audio.addEventListener("pause", syncPlayButtons);
  audio.addEventListener("ended", syncPlayButtons);

  audio.addEventListener("loadedmetadata", function () {
    if (isFinite(audio.duration) && durTimeEl) {
      durTimeEl.textContent = fmtTime(audio.duration);
    }
  });

  if (seekSlider) {
    seekSlider.addEventListener("input", function () {
      if (!isFinite(audio.duration) || audio.duration <= 0) return;
      const pct = parseFloat(seekSlider.value) / 1000.0;
      audio.currentTime = pct * audio.duration;
    });
  }

  audio.addEventListener("timeupdate", function () {
    const t = audio.currentTime || 0;
    if (curTimeEl) curTimeEl.textContent = fmtTime(t);
    if (seekSlider && isFinite(audio.duration) && audio.duration > 0) {
      seekSlider.value = String(Math.round((t / audio.duration) * 1000));
    }

    let activeCard = null;
    for (let i = 0; i < turnCards.length; i++) {
      const card = turnCards[i];
      const start = parseFloat(card.dataset.start || "0");
      const end = parseFloat(card.dataset.end || "0");
      const match = t >= start && t <= end + 0.18;
      card.classList.toggle("speaking", match);
      if (match) activeCard = card;
    }

    if (activeCard && liveSpeakerEl) {
      const speaker = activeCard.dataset.speaker || "";
      const topic = activeCard.dataset.topic || "";
      liveSpeakerEl.textContent = speaker + (topic ? " · " + topic : "");
    }
  });

  turnCards.forEach(function (card) {
    card.addEventListener("click", function () {
      const start = parseFloat(card.dataset.start || "0");
      audio.currentTime = start;
      audio.play().catch(function () {});
    });
  });
})();
