const startBtn   = document.getElementById("startBtn");
const nextBtn    = document.getElementById("nextBtn");
const submitBtn  = document.getElementById("submit");
const overrideBtn= document.getElementById("override");

const game    = document.getElementById("game");
const doneEl  = document.getElementById("done");
const promptEl= document.getElementById("prompt");
const metaEl  = document.getElementById("meta");
const leadinEl= document.getElementById("leadin");
const ansEl   = document.getElementById("answer");
const fbEl    = document.getElementById("feedback");
const thetaEl = document.getElementById("theta");

let answered = false;  // tracks if current question is already graded
// Dependent dropdown options
const CATEGORY_MAP = {
  "Literature": {
    sub: [
      "All",
      "American Literature", "British Literature", "Classical Literature",
      "European Literature", "World Literature", "Other Literature"
    ],
    alt: [
      "All",
      "Drama", "Long Fiction", "Poetry", "Short Fiction", "Misc Literature"
    ]
  },
  "History": {
    sub: [
      "All",
      "American History", "Ancient History", "European History",
      "World History", "Other History"
    ],
    alt: ["All"]        // no alternates shown in your sheet
  },
  "Science": {
    sub: [
      "All",
      "Biology", "Chemistry", "Physics", "Other Science"
    ],
    alt: [
      "All",
      "Math", "Astronomy", "Computer Science", "Earth Science",
      "Engineering", "Misc Science"
    ]
  },
  "Fine Arts": {
    sub: [
      "All",
      "Visual Fine Arts", "Auditory Fine Arts", "Other Fine Arts"
    ],
    alt: [
      "All",
      "Architecture", "Dance", "Film", "Jazz", "Musicals",
      "Opera", "Photography", "Misc Arts"
    ]
  },
  "Religion":      { sub: ["All"], alt: ["All"] },
  "Mythology":     { sub: ["All"], alt: ["All"] },
  "Philosophy":    { sub: ["All"], alt: ["All"] },
  "Social Science": {
    sub: ["All"],   // your sheet only shows alternates
    alt: [
      "All",
      "Anthropology", "Economics", "Linguistics",
      "Psychology", "Sociology", "Other Social Science"
    ]
  },
  "Trash": {        // Pop culture
    sub: [
      "All",
      "Movies", "Music", "Sports", "Television", "Video Games",
      "Other Pop Culture"
    ],
    alt: ["All"]    // no alternates in your sheet
  }
};
function fillSelect(selectEl, options) {
  selectEl.innerHTML = "";
  for (const label of options) {
    const opt = document.createElement("option");
    opt.textContent = label;
    opt.value = label;
    selectEl.appendChild(opt);
  }
  selectEl.value = "All";
}
const categoryEl = document.getElementById("category");
const subEl      = document.getElementById("subcategory");
const altsEl     = document.getElementById("alts");

function refreshDependentSelects() {
  const cat = categoryEl.value;
  if (cat === "All") {
    // disable & reset when Category = All
    subEl.disabled = true;
    altsEl.disabled = true;
    fillSelect(subEl, ["All"]);
    fillSelect(altsEl, ["All"]);
    return;
  }
  // enable and populate from map
  const cfg = CATEGORY_MAP[cat] || { sub: ["All"], alt: ["All"] };
  subEl.disabled = false;
  altsEl.disabled = false;
  fillSelect(subEl, cfg.sub);
  fillSelect(altsEl, cfg.alt);
}

// initial state
refreshDependentSelects();

// on change
categoryEl.addEventListener("change", refreshDependentSelects);


async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  return await r.json();
}

async function getJSON(url) {
  const r = await fetch(url);
  return await r.json();
}

startBtn.onclick = async () => {
  const category = categoryEl.value; // "All" allowed
  const subVal   = subEl.value;      // now a select
  const altVal   = altsEl.value;     // now a select

  const sub  = (subVal && subVal !== "All") ? subVal : null;
  // backend used to accept a list; we'll still send an array if not "All"
  const alts = (altVal && altVal !== "All") ? [altVal] : null;

  const rounds = parseInt(document.getElementById("rounds").value || "12", 10);

  await postJSON("/api/start", {
    category,
    subcategory: sub,
    alternateSubcategories: alts,
    rounds
  });

  // reset UI
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

  // session done
  if (data.done) {
    game.style.display = "none";
    doneEl.style.display = "block";

    const fs = document.getElementById("finalStats");
    if (fs) {
      // base line (θ, SE, CI)
      let html = `Final θ ≈ ${data.theta}`;
      if (data.se && data.ci) {
        html += ` SE ≈ ${data.se} 95% CI ≈ [${data.ci[0]}, ${data.ci[1]}]`;
      }

      // score on its own line, bigger and black
      if (typeof data.score10 !== "undefined") {
        html += `<div style="margin-top:0.75rem; font-size:1.2rem; font-weight:600; color:#000;">
          Score (1–10): ${data.score10}
        </div>`;
      }

      // ppb guesses each on its own line
      if (data.ppb_guesses) {
        html += `<div style="margin-top:0.75rem; line-height:1.4;">`;
        html += `<div>MS: ${data.ppb_guesses.middle_school}</div>`;
        html += `<div>HS Easy: ${data.ppb_guesses.hs_easy}</div>`;
        html += `<div>HS Regular: ${data.ppb_guesses.hs_regular}</div>`;
        html += `<div>1-dot college: ${data.ppb_guesses.college_1dot}</div>`;
        html += `<div>2-dot college: ${data.ppb_guesses.college_2dot}</div>`;
        html += `<div>3-dot college: ${data.ppb_guesses.college_3dot}</div>`;
        html += `</div>`;
      }

      fs.innerHTML = html;
    }

    return;
  }


  // re-enable override for this new question
  overrideBtn.disabled = false;

  if (data.error) {
    promptEl.textContent = "No usable item this round. Click Next.";
    metaEl.textContent = "";
    leadinEl.textContent = "";
    return;
  }

  // show level + part label, e.g. "High School Regular (Medium)"
  const fallbackTag = data.mode && data.mode.includes("fallback") ? " (fallback)" : "";
  const partText = data.partLabel ? ` (${data.partLabel})` : "";

  metaEl.textContent =
    `[${data.meta.set} • ${data.meta.year} • Packet ${data.meta.packet} • Q#${data.meta.qnum}]  |  ` +
    `Level by θ: ${data.level}${partText}  |  θ≈${Number(data.theta).toFixed(2)}${fallbackTag}`;

  leadinEl.textContent = data.showLeadin && data.leadin ? `Leadin: ${data.leadin}` : "";
  promptEl.textContent = data.prompt;

  fbEl.textContent = "";
  ansEl.value = "";
  ansEl.focus();

  answered = false;  // reset for this question
}


submitBtn.onclick = async () => {
  // allow empty submissions now
  const answer = ansEl.value;
  const res = await postJSON("/api/answer", { answer });
  if (res.prompt) {
    fbEl.innerHTML = "🟡 Prompt — be more specific (or click <code>Mark Correct (Y)</code> if truly right).";
    return;
  }
  showResult(res);
};

overrideBtn.onclick = async () => {
  if (overrideBtn.disabled) return;
  const answer = ansEl.value;
  const res = await postJSON("/api/answer", { answer, override: "Y" });
  showResult(res);
  overrideBtn.disabled = true;   // disable for this question
};

function showResult(res) {
  if (res.correct) {
    fbEl.innerHTML = `✅ Accepted!`;
  } else {
    fbEl.innerHTML = `❌ Incorrect. Official: <i>${res.officialAnswer}</i>`;
  }
  thetaEl.textContent =
    `θ ≈ ${res.theta}` + (res.se ? `   SE ≈ ${res.se}   95% CI ≈ [${res.ci[0]}, ${res.ci[1]}]` : "");

  answered = true;  // now Enter should go to next
}

nextBtn.onclick = async () => {
  answered = false;
  await loadNext();
};

// Enter = submit first, then next
ansEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    if (!answered) {
      submitBtn.click();
    } else {
      nextBtn.click();
    }
  }
});


