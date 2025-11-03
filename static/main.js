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
let answered = false;


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
  const category = document.getElementById("category").value;
  const sub      = document.getElementById("subcategory").value.trim() || null;
  const altsTxt  = document.getElementById("alts").value.trim();
  const alts     = altsTxt ? altsTxt.split(",").map(s=>s.trim()).filter(Boolean) : null;
  const rounds   = parseInt(document.getElementById("rounds").value || "12", 10);

  // 🔄 tell server to reset state
  await postJSON("/api/start", {
    category,
    subcategory: sub,
    alternateSubcategories: alts,
    rounds
  });

  // 🔄 reset client state/UI
  answered = false;
  metaEl.textContent   = "";
  leadinEl.textContent = "";
  promptEl.textContent = "";
  fbEl.textContent     = "";
  thetaEl.textContent  = "";
  ansEl.value          = "";

  doneEl.style.display = "none";
  game.style.display   = "block";

  await loadNext();
};

async function loadNext() {
  const data = await getJSON("/api/next");
  if (data.done) {
    game.style.display = "none";
    doneEl.style.display = "block";

    const fs = document.getElementById("finalStats");
    if (data.se && data.ci) {
      fs.textContent = `Final θ ≈ ${data.theta}   SE ≈ ${data.se}   95% CI ≈ [${data.ci[0]}, ${data.ci[1]}]`;
    } else {
      fs.textContent = `Final θ ≈ ${data.theta}`;
    }
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
  overrideBtn.disabled = true;  // 🚫 disable after click
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

  answered = true; // mark question as done
}

nextBtn.onclick = async () => {
  answered = false;    // reset for next question when clicking Next
  await loadNext();
};

// ✅ keep only this one declaration (the earlier one at the top)
ansEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    if (!answered) {
      submitBtn.click(); // first Enter → submit
    } else {
      nextBtn.click();   // next Enter → go to next
      answered = false;  // reset for the following round
    }
  }
});

// Also reset when a new item loads
async function loadNext() {
  const data = await getJSON("/api/next");
  if (data.done) {
    game.style.display = "none";
    doneEl.style.display = "block";


    const fs = document.getElementById("finalStats");
    if (data.se && data.ci) {
      fs.textContent = `Final θ ≈ ${data.theta}   SE ≈ ${data.se}   95% CI ≈ [${data.ci[0]}, ${data.ci[1]}]`;
    } else {
      fs.textContent = `Final θ ≈ ${data.theta}`;
    }
    return;
  }
  overrideBtn.disabled = false;  // ♻️ re-enable for new question

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

  answered = false;   // ✅ reset here too on every new item
}