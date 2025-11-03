const startBtn = document.getElementById("startBtn");
const nextBtn  = document.getElementById("nextBtn");
const submitBtn= document.getElementById("submit");
const overrideBtn = document.getElementById("override");

const game   = document.getElementById("game");
const doneEl = document.getElementById("done");
const promptEl=document.getElementById("prompt");
const metaEl = document.getElementById("meta");
const leadinEl=document.getElementById("leadin");
const ansEl  = document.getElementById("answer");
const fbEl   = document.getElementById("feedback");
const thetaEl= document.getElementById("theta");

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json"},
    body: JSON.stringify(body || {})
  });
  return await r.json();
}
async function getJSON(url) {
  const r = await fetch(url);
  return await r.json();
}

startBtn.onclick = async () => {
  const category = document.getElementById("category").value;     // "All" allowed
  const sub      = document.getElementById("subcategory").value.trim() || null;
  const altsTxt  = document.getElementById("alts").value.trim();
  const alts     = altsTxt ? altsTxt.split(",").map(s=>s.trim()).filter(Boolean) : null;
  const rounds   = parseInt(document.getElementById("rounds").value || "12", 10);

  await postJSON("/api/start", {
    category,
    subcategory: sub,
    alternateSubcategories: alts,
    rounds
  });

  game.style.display = "block";
  doneEl.style.display = "none";
  fbEl.textContent = "";
  ansEl.value = "";
  await loadNext();
};

async function loadNext() {
  const data = await getJSON("/api/next");
  if (data.done) {
    game.style.display = "none";
    doneEl.style.display = "block";
    return;
  }
  if (data.error) {
    promptEl.textContent = "No usable item this round. Click Next.";
    metaEl.textContent = "";
    leadinEl.textContent = "";
    return;
  }

  const fallbackTag = data.mode && data.mode.includes("any") ? " (fallback)" : "";
  metaEl.textContent =
    `[${data.meta.set} • ${data.meta.year} • Packet ${data.meta.packet} • Q#${data.meta.qnum}]  |  ` +
    `Level by θ: ${data.level}  |  θ≈${Number(data.theta).toFixed(2)}${fallbackTag}`;

  leadinEl.textContent = data.showLeadin && data.leadin ? `Leadin: ${data.leadin}` : "";
  promptEl.textContent = data.prompt;

  fbEl.textContent = "";
  ansEl.value = "";
  ansEl.focus();
}

submitBtn.onclick = async () => {
  const answer = ansEl.value.trim();
  const res = await postJSON("/api/answer", { answer });
  if (res.prompt) {
    fbEl.innerHTML = "🟡 Prompt — be more specific (or click <code>Mark Correct (Y)</code> if truly right).";
    return;
  }
  showResult(res);
};

overrideBtn.onclick = async () => {
  const answer = ansEl.value.trim();
  const res = await postJSON("/api/answer", { answer, override: "Y" });
  showResult(res);
};

function showResult(res) {
  if (res.correct) {
    fbEl.innerHTML = `✅ Accepted!`;
  } else {
    fbEl.innerHTML = `❌ Incorrect. Official: <i>${res.officialAnswer}</i>`;
  }
  thetaEl.textContent =
    `θ ≈ ${res.theta}` + (res.se ? `   SE ≈ ${res.se}   95% CI ≈ [${res.ci[0]}, ${res.ci[1]}]` : "");
}

nextBtn.onclick = loadNext;

ansEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    submitBtn.click();
  }
});