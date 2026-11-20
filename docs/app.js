(() => {
  const REPO_API = "https://api.github.com/repos/alzheimeer/nikk-slicer/releases/latest";
  const RELEASES_FALLBACK = "https://github.com/alzheimeer/nikk-slicer/releases/latest";

  function detectOS() {
    const plat = (
      (navigator.userAgentData && navigator.userAgentData.platform) ||
      navigator.platform ||
      navigator.userAgent ||
      ""
    ).toLowerCase();
    if (plat.includes("mac") || plat.includes("darwin")) return "macos";
    if (plat.includes("win")) return "windows";
    return "windows";
  }

  function formatMB(bytes) {
    if (!bytes || typeof bytes !== "number") return null;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  const userOS = detectOS();

  const els = {
    versionBadge: document.getElementById("release-version-badge"),
    downloadsVersion: document.getElementById("downloads-version-label"),
    releaseMeta: document.getElementById("release-meta-line"),
    primaryBtn: document.getElementById("primary-download-btn"),
    primaryIcon: document.getElementById("primary-os-icon"),
    primaryLabel: document.getElementById("primary-download-label"),
    primaryMeta: document.getElementById("primary-download-meta"),
    secondaryBtn: document.getElementById("secondary-download-btn"),
    secondaryLabel: document.getElementById("secondary-download-label"),
    secondaryMeta: document.getElementById("secondary-download-meta"),
    winCard: document.getElementById("card-windows"),
    macCard: document.getElementById("card-macos"),
    winCardBtn: document.getElementById("win-download-card-btn"),
    macCardBtn: document.getElementById("mac-download-card-btn"),
    winSize: document.getElementById("win-size-badge"),
    macSize: document.getElementById("mac-size-badge"),
  };

  function applyDownloadUI({ tag, winUrl, macUrl, winSize, macSize }) {
    const verText = tag || "Último Release";
    if (els.versionBadge) els.versionBadge.textContent = verText;
    if (els.downloadsVersion) els.downloadsVersion.textContent = verText;

    if (els.winCardBtn) els.winCardBtn.href = winUrl;
    if (els.macCardBtn) els.macCardBtn.href = macUrl;
    if (els.winSize && winSize) els.winSize.textContent = `${winSize} · Inno Setup`;
    if (els.macSize && macSize) els.macSize.textContent = `${macSize} · DMG`;

    const isMac = userOS === "macos";
    if (els.winCard && !isMac) els.winCard.classList.add("recommended");
    if (els.macCard && isMac) els.macCard.classList.add("recommended");

    if (isMac) {
      if (els.primaryBtn) els.primaryBtn.href = macUrl;
      if (els.primaryIcon) els.primaryIcon.textContent = "";
      if (els.primaryLabel) els.primaryLabel.textContent = "Descargar para macOS (.dmg)";
      if (els.primaryMeta) {
        els.primaryMeta.textContent = `${verText}${macSize ? ` · ${macSize}` : ""} · Apple Silicon & Intel`;
      }
      if (els.secondaryBtn) els.secondaryBtn.href = winUrl;
      if (els.secondaryLabel) els.secondaryLabel.textContent = "Descargar para Windows (.exe)";
      if (els.secondaryMeta) {
        els.secondaryMeta.textContent = `${verText}${winSize ? ` · ${winSize}` : ""} · Windows 10/11 x64`;
      }
    } else {
      if (els.primaryBtn) els.primaryBtn.href = winUrl;
      if (els.primaryIcon) els.primaryIcon.textContent = "⊞";
      if (els.primaryLabel) els.primaryLabel.textContent = "Descargar para Windows (.exe)";
      if (els.primaryMeta) {
        els.primaryMeta.textContent = `${verText}${winSize ? ` · ${winSize}` : ""} · Windows 10/11 x64`;
      }
      if (els.secondaryBtn) els.secondaryBtn.href = macUrl;
      if (els.secondaryLabel) els.secondaryLabel.textContent = "Descargar para macOS (.dmg)";
      if (els.secondaryMeta) {
        els.secondaryMeta.textContent = `${verText}${macSize ? ` · ${macSize}` : ""} · Apple Silicon & Intel`;
      }
    }
  }

  // Initial OS-aware defaults before API resolves
  applyDownloadUI({
    tag: "Último Release",
    winUrl: RELEASES_FALLBACK,
    macUrl: RELEASES_FALLBACK,
    winSize: null,
    macSize: null,
  });

  fetch(REPO_API, { headers: { Accept: "application/vnd.github+json" } })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((data) => {
      const tag = data.tag_name || "Último Release";
      const assets = Array.isArray(data.assets) ? data.assets : [];
      const winAsset = assets.find((a) => /\.exe$/i.test(a.name || ""));
      const macAsset = assets.find((a) => /\.dmg$/i.test(a.name || ""));

      applyDownloadUI({
        tag,
        winUrl: (winAsset && winAsset.browser_download_url) || RELEASES_FALLBACK,
        macUrl: (macAsset && macAsset.browser_download_url) || RELEASES_FALLBACK,
        winSize: formatMB(winAsset && winAsset.size),
        macSize: formatMB(macAsset && macAsset.size),
      });

      if (els.releaseMeta) {
        const pubDate = data.published_at
          ? new Date(data.published_at).toLocaleDateString("es-ES", {
              year: "numeric",
              month: "short",
              day: "numeric",
            })
          : "";
        els.releaseMeta.textContent = `${tag}${pubDate ? ` · publicado ${pubDate}` : ""}`;
      }
    })
    .catch(() => {
      if (els.releaseMeta) {
        els.releaseMeta.textContent = "Descarga directa desde GitHub Releases";
      }
    });

  // MCP JSON Interactive Switcher + Copy
  const mcpConfigs = {
    http: {
      hint: 'Conecta con Nikk Slicer abierto en <code>http://127.0.0.1:8000/mcp</code> (Streamable HTTP).',
      json: JSON.stringify(
        {
          mcpServers: {
            "nikk-slicer": {
              url: "http://127.0.0.1:8000/mcp",
            },
          },
        },
        null,
        2
      ),
    },
    stdio: {
      hint: "Ejecuta el servidor MCP localmente por <code>stdio</code> incluso con la ventana cerrada.",
      json: JSON.stringify(
        {
          mcpServers: {
            "nikk-slicer": {
              command: "python3",
              args: ["-m", "backend.app.mcp_server"],
              env: {
                PYTHONPATH: "/ruta/a/nikk-slicer",
              },
            },
          },
        },
        null,
        2
      ),
    },
  };

  let activeTab = "http";
  const codeEl = document.getElementById("mcp-json-code");
  const hintEl = document.getElementById("mcp-hint-text");
  const copyBtn = document.getElementById("copy-mcp-btn");
  const tabBtns = document.querySelectorAll("[data-mcp-tab]");

  function renderMcpTab(tabKey) {
    activeTab = tabKey;
    const cfg = mcpConfigs[tabKey];
    if (codeEl) codeEl.textContent = cfg.json;
    if (hintEl) hintEl.innerHTML = cfg.hint;
    tabBtns.forEach((btn) => {
      const isCurrent = btn.getAttribute("data-mcp-tab") === tabKey;
      btn.classList.toggle("active", isCurrent);
      btn.setAttribute("aria-selected", String(isCurrent));
    });
  }

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      renderMcpTab(btn.getAttribute("data-mcp-tab") || "http");
    });
  });

  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const text = mcpConfigs[activeTab].json;
      try {
        await navigator.clipboard.writeText(text);
        copyBtn.textContent = "✓ Copiado";
      } catch {
        copyBtn.textContent = "Error al copiar";
      }
      setTimeout(() => {
        copyBtn.textContent = "Copiar JSON";
      }, 1800);
    });
  }

  renderMcpTab("http");

  // IntersectionObserver fallback only when CSS scroll-driven animations are unsupported
  const supportsViewTimeline =
    typeof CSS !== "undefined" &&
    typeof CSS.supports === "function" &&
    CSS.supports("(animation-timeline: view()) and (animation-range: entry)");

  if (
    !supportsViewTimeline &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: no-preference)").matches
  ) {
    const targets = document.querySelectorAll(".reveal");
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("js-visible");
            entry.target.classList.remove("js-hidden");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.12 }
    );

    targets.forEach((el) => {
      el.classList.add("js-hidden");
      observer.observe(el);
    });
  }
})();
