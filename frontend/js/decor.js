/** 装饰脚本：给页面撒下飘落的花瓣。
 *
 * 只在 <body data-petals="on"> 的页面启用（首页、登记页）。
 * 系统开启「减少动态效果」时直接不生成，避免晕动不适。
 * 花瓣层是 fixed + pointer-events:none，不会挡住任何点击。
 */
(function () {
  const body = document.body;
  if (!body || body.dataset.petals !== "on") return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const count = window.innerWidth < 700 ? 7 : 12;
  const layer = document.createElement("div");
  layer.className = "petals";
  layer.setAttribute("aria-hidden", "true");

  for (let i = 0; i < count; i += 1) {
    const petal = document.createElement("span");
    petal.className = "petal";
    const size = 7 + Math.random() * 9;
    petal.style.width = `${size}px`;
    petal.style.height = `${size}px`;
    petal.style.left = `${Math.random() * 100}%`;
    petal.style.setProperty("--drift", `${(Math.random() - 0.5) * 200}px`);
    petal.style.animationDuration = `${12 + Math.random() * 14}s`;
    // 负延迟让页面一打开就已经"下着花瓣"，而不是等十几秒才出现
    petal.style.animationDelay = `${-Math.random() * 16}s`;
    petal.style.opacity = `${0.22 + Math.random() * 0.38}`;
    layer.appendChild(petal);
  }

  body.appendChild(layer);
})();
