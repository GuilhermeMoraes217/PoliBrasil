const config = window.POLI_FIREBASE_CONFIG || {};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const ROUND_MS = 10000;

const state = {
  auth: null,
  firebase: null,
  database: null,
  firebaseDatabase: null,
  user: null,
  profile: null,
  room: null,
  roomCode: null,
  context: null,
  contextPollTimer: null,
  bomb: null,
  bombPollTimer: null,
  bombTimer: null,
  bombTypingUnsubscribe: null,
  bombTypingValue: "",
  bombTypingByUid: {},
  lastBombFeedback: null,
  lastBombFinish: null,
  pollTimer: null,
  rematchPollTimer: null,
  pendingRematch: null,
  pendingJoinCode: null,
  pendingBombJoinCode: null,
  pollInFlight: false,
  timer: null,
  selectedMode: "translation",
  selectedDifficulty: "easy",
  selectedCategory: "all",
  lastRound: -1,
  lastFeedback: null,
  serverOffset: 0,
  muted: localStorage.getItem("poli-muted") === "true",
  musicTrack: localStorage.getItem("poli-music-track") || "off",
  musicTimer: null,
  audioContext: null,
  musicStep: 0,
  apiToken: null,
  demo: !config.apiKey || new URLSearchParams(location.search).has("demo")
};

const screens = {
  home: $("#home-screen"),
  lobby: $("#lobby-screen"),
  game: $("#game-screen"),
  context: $("#context-screen"),
  bomb: $("#bomb-screen")
};

boot();

async function boot() {
  bindInterface();
  await connectFirebase();
  renderIdentity();
  await loadDashboard();
  openInvite();
  scheduleRematchRefresh();
}

function bindInterface() {
  $$("[data-open-modal]").forEach((button) => button.addEventListener("click", () => {
    if (!requireGoogleLogin()) return;
    if (button.dataset.mode) selectMode(button.dataset.mode);
    if (button.dataset.openModal === "create") setModePickerVisibility(!button.dataset.mode);
    $(`#${button.dataset.openModal}-modal`).showModal();
  }));
  $$(".close-modal").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
  $$(".mode-choice").forEach((button) => button.addEventListener("click", () => selectMode(button.dataset.choice)));
  $$(".difficulty-choice").forEach((button) => button.addEventListener("click", () => selectDifficulty(button.dataset.difficulty)));
  $$("[data-go-home]").forEach((button) => button.addEventListener("click", leaveAndGoHome));
  $("#create-room").addEventListener("click", createRoom);
  $("#join-room").addEventListener("click", joinRoom);
  $("#auth-button").addEventListener("click", handleAuth);
  $("#answer-form").addEventListener("submit", submitAnswer);
  $("#room-code").addEventListener("click", copyCode);
  $("#copy-invite").addEventListener("click", copyInvite);
  $("#mute-button").addEventListener("click", toggleMute);
  $("#music-track").addEventListener("change", changeMusicTrack);
  $("#rematch-button").addEventListener("click", requestRematch);
  $("#accept-rematch").addEventListener("click", acceptRematch);
  $("#decline-rematch").addEventListener("click", declineRematch);
  $("#finish-home").addEventListener("click", leaveAndGoHome);
  $("#open-context").addEventListener("click", openContextModal);
  $("#start-context").addEventListener("click", startContext);
  $("#join-context").addEventListener("click", joinContext);
  $("#leave-context").addEventListener("click", leaveContext);
  $("#context-form").addEventListener("submit", submitContextWord);
  $("#open-bomb").addEventListener("click", openBombModal);
  $("#create-bomb").addEventListener("click", createBomb);
  $("#join-bomb").addEventListener("click", joinBomb);
  $("#bomb-ready").addEventListener("click", toggleBombReady);
  $("#bomb-start").addEventListener("click", startBombMatch);
  $("#bomb-rematch").addEventListener("click", requestBombRematch);
  $("#leave-bomb").addEventListener("click", leaveBomb);
  $("#bomb-form").addEventListener("submit", submitBombAnswer);
  $("#bomb-input").addEventListener("input", publishBombTyping);
  $("#copy-bomb-invite").addEventListener("click", copyBombInvite);
  document.addEventListener("pointerdown", startMusic, { once: true });
  window.addEventListener("beforeunload", notifyLeaveOnUnload);
  renderMute();
  $("#music-track").value = state.musicTrack;
}

async function connectFirebase() {
  if (state.demo) {
    state.user = { uid: `demo-${Date.now()}`, displayName: "Demo Player", photoURL: "" };
    $("#connection-label").textContent = "demo local";
    return;
  }
  try {
    const appSdk = await import("https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js");
    const authSdk = await import("https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js");
    const databaseSdk = await import("https://www.gstatic.com/firebasejs/10.12.5/firebase-database.js");
    const app = appSdk.initializeApp(config);
    state.firebase = authSdk;
    state.firebaseDatabase = databaseSdk;
    state.database = databaseSdk.getDatabase(app);
    state.auth = authSdk.getAuth(app);
    await new Promise((resolve) => authSdk.onAuthStateChanged(state.auth, async (user) => {
      state.user = user;
      renderIdentity();
      await loadDashboard();
      resolve();
    }));
    $("#connection-label").textContent = "firebase online";
  } catch (error) {
    console.error(error);
    state.user = null;
    $("#connection-label").textContent = "firebase offline";
    toast("Firebase indisponível. Tente novamente em instantes.");
  }
}

async function login() {
  if (state.demo) return toast("Modo demo ativo");
  try {
    await state.firebase.signInWithPopup(state.auth, new state.firebase.GoogleAuthProvider());
    state.user = state.auth.currentUser;
    renderIdentity();
    await loadDashboard();
    await completePendingJoin();
    await completePendingBombJoin();
    toast("Login realizado");
  } catch (error) {
    console.error(error);
    toast("Não foi possível entrar com Google");
  }
}

async function handleAuth() {
  if (state.user?.displayName && !state.demo) return logout();
  return login();
}

async function logout() {
  try {
    if (state.roomCode) await leaveAndGoHome();
    if (state.context) leaveContext();
    if (state.bomb) await leaveBomb();
    await state.firebase.signOut(state.auth);
    state.user = null;
    state.profile = null;
    renderIdentity();
    renderHistoryMessage("Faça login para registrar partidas.");
    toast("Logout realizado");
  } catch (error) {
    console.error(error);
    toast("Não foi possível sair");
  }
}

async function ensureUser() {
  if (state.demo) return state.user;
  if (isGoogleUser()) return state.user;
  throw new Error("Faça login com Google para jogar");
}

async function api(path, options = {}) {
  await ensureUser();
  const token = state.demo ? state.user.uid : await state.user.getIdToken();
  state.apiToken = token;
  const response = await fetch(`/api${path}`, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error || "Falha na operação");
    error.payload = payload;
    throw error;
  }
  return payload;
}

function renderIdentity() {
  const loggedWithGoogle = state.user?.displayName && !state.demo;
  $("#user-label").textContent = loggedWithGoogle ? shortName(state.user.displayName) : "";
  $("#auth-button").textContent = loggedWithGoogle ? "logout()" : "login_google()";
  $("#topbar-profile").classList.toggle("hidden", !loggedWithGoogle);
  if (loggedWithGoogle) {
    renderAvatar($("#topbar-avatar"), { photo: state.user.photoURL, progression: state.profile?.progression }, "P");
    $("#topbar-level").textContent = levelLabel(state.profile?.progression);
  }
}

function selectMode(mode) {
  state.selectedMode = mode;
  $$(".mode-choice").forEach((button) => button.classList.toggle("selected", button.dataset.choice === mode));
}

function setModePickerVisibility(visible) {
  $("#mode-picker").classList.toggle("hidden", !visible);
}

function selectDifficulty(difficulty) {
  state.selectedDifficulty = difficulty;
  $$(".difficulty-choice").forEach((button) => button.classList.toggle("selected", button.dataset.difficulty === difficulty));
}

async function createRoom() {
  try {
    state.selectedCategory = $("#category-choice").value;
    const { room } = await api("/rooms", { method: "POST", body: { mode: state.selectedMode, difficulty: state.selectedDifficulty, category: state.selectedCategory, demo: state.demo } });
    $("#create-modal").close();
    startRoom(room);
  } catch (error) {
    toast(error.message);
  }
}

async function joinRoom() {
  const code = $("#join-code").value.trim().toUpperCase();
  if (code.length !== 6) return toast("Digite um código de 6 caracteres");
  if (!state.demo && !isGoogleUser()) {
    state.pendingJoinCode = code;
    toast("Faça login com Google para entrar na sala");
    return login();
  }
  try {
    const { room } = await api(`/rooms/${code}/join`, { method: "POST", body: {} });
    $("#join-modal").close();
    startRoom(room);
  } catch (error) {
    toast(error.message);
  }
}

async function startContext() {
  try {
    const { context } = await api("/contexts", {
      method: "POST",
      body: { difficulty: $("#context-difficulty").value, category: $("#context-category").value }
    });
    $("#context-modal").close();
    enterContext(context);
  } catch (error) {
    toast(error.message);
  }
}

async function openContextModal() {
  if (!requireGoogleLogin()) return;
  $("#context-modal").showModal();
  await loadOpenContexts();
}

async function loadOpenContexts() {
  const element = $("#context-open-rooms");
  try {
    const { contexts } = await api("/contexts");
    element.innerHTML = contexts.length ? `
      <p>// SUAS_SALAS_ABERTAS</p>
      ${contexts.map((context) => `
        <button class="context-room" type="button" data-context-code="${context.code}">
          <b>#${context.code}</b>
          <span>${context.players} PLAYERS · ${context.guesses} TENTATIVAS</span>
        </button>
      `).join("")}
    ` : "";
    element.querySelectorAll("[data-context-code]").forEach((button) => button.addEventListener("click", () => resumeContext(button.dataset.contextCode)));
  } catch (error) {
    element.innerHTML = "";
  }
}

async function resumeContext(code) {
  try {
    const { context } = await api(`/contexts/${code}`);
    $("#context-modal").close();
    enterContext(context);
  } catch (error) {
    toast(error.message);
  }
}

async function joinContext() {
  const code = $("#context-join-code").value.trim().toUpperCase();
  if (code.length !== 6) return toast("Digite um código de 6 caracteres");
  try {
    const { context } = await api(`/contexts/${code}/join`, { method: "POST", body: {} });
    $("#context-modal").close();
    enterContext(context);
  } catch (error) {
    toast(error.message);
  }
}

function enterContext(context) {
  state.context = context;
  renderContext();
  showScreen("context");
  focusInput("#context-input");
  clearTimeout(state.contextPollTimer);
  state.contextPollTimer = setTimeout(refreshContext, 900);
}

async function refreshContext() {
  if (!state.context) return;
  try {
    state.context = (await api(`/contexts/${state.context.code}`)).context;
    renderContext();
    state.contextPollTimer = setTimeout(refreshContext, document.hidden ? 4000 : 900);
  } catch (error) {
    toast(error.message);
  }
}

async function submitContextWord(event) {
  event.preventDefault();
  const input = $("#context-input");
  const value = input.value.trim();
  if (!value || !state.context) return;
  try {
    const { suggestions, knownEnglish } = await api(`/contexts/${state.context.code}/suggest`, { method: "POST", body: { value } });
    if (suggestions.length && !suggestions.some((item) => item.en.toLowerCase() === value.toLowerCase())) {
      return renderContextSuggestion(suggestions[0]);
    }
    if (!knownEnglish) {
      $("#context-feedback").textContent = "Ainda não encontrei essa palavra. Tente outro termo em português ou uma palavra em inglês cadastrada.";
      return;
    }
    await sendContextGuess(value);
  } catch (error) {
    $("#context-feedback").textContent = error.message;
  }
}

function renderContextSuggestion(suggestion) {
  const element = $("#context-suggestion");
  element.classList.remove("hidden");
  element.innerHTML = `<p>Você quis dizer <b>${escapeHtml(suggestion.en)}</b> em inglês?</p><button class="button primary compact" type="button">ACEITAR E ENVIAR</button>`;
  element.querySelector("button").addEventListener("click", () => sendContextGuess(suggestion.en));
}

async function sendContextGuess(value) {
  try {
    state.context = (await api(`/contexts/${state.context.code}/guess`, { method: "POST", body: { value } })).context;
    $("#context-input").value = "";
    $("#context-suggestion").classList.add("hidden");
    renderContext();
    focusInput("#context-input");
    playSound(state.context.status === "solved" ? "gain" : "hit");
  } catch (error) {
    $("#context-feedback").textContent = error.message;
  }
}

function renderContext() {
  const context = state.context;
  $("#context-meta").textContent = `ROOM #${context.code} · ${context.difficulty.toUpperCase()} · ${context.category.toUpperCase()}`;
  $("#context-count").textContent = context.guesses.length;
  $("#context-scoreboard").innerHTML = Object.values(context.players).sort((one, two) => two.score - one.score).map((player) => `
    <span>${escapeHtml(player.name)} · ${player.score || 0} XP</span>
  `).join("");
  $("#context-guesses").innerHTML = context.guesses.length ? [...context.guesses].reverse().map((guess) => `
    <li title="${escapeHtml(guess.translation)}">
      <b class="context-rank">${guess.proximity}</b>
      <span class="context-word">${escapeHtml(guess.word)}</span>
      <span class="context-player">${escapeHtml(guess.player)} +${guess.points}</span>
      <button class="context-info" type="button" title="${escapeHtml(guess.translation)}" aria-label="Tradução: ${escapeHtml(guess.translation)}">i</button>
      <span class="context-meter"><i style="width:${100 - guess.proximity}%"></i></span>
    </li>
  `).join("") : '<li class="empty">Nenhuma tentativa ainda.</li>';
  $("#context-feedback").textContent = context.lastSolved
    ? `${context.lastSolved.player} encontrou ${context.lastSolved.word} = ${context.lastSolved.translation} e venceu!`
    : context.learningNote || "Quanto menor o número, mais perto você está. Zero libera uma nova palavra.";
  $("#context-feedback").className = context.lastSolved ? "feedback correct" : "feedback";
  $("#context-input").disabled = context.status === "finished";
  focusInput("#context-input");
}

function leaveContext() {
  clearTimeout(state.contextPollTimer);
  state.context = null;
  $("#context-input").value = "";
  $("#context-suggestion").classList.add("hidden");
  showScreen("home");
}

async function openBombModal() {
  if (!requireGoogleLogin()) return;
  $("#bomb-modal").showModal();
  await loadOpenBombs();
}

async function loadOpenBombs() {
  const element = $("#bomb-open-rooms");
  try {
    const { bombs } = await api("/bombs");
    element.innerHTML = bombs.length ? `
      <p>// SUAS_SALAS_ABERTAS</p>
      ${bombs.map((bomb) => `
        <button class="context-room" type="button" data-bomb-code="${bomb.code}">
          <b>#${bomb.code}</b>
          <span>${bomb.players} PLAYERS · ${bomb.language.toUpperCase()} · ${bombLevelLabel(bomb)} · ${bomb.status.toUpperCase()}</span>
        </button>
      `).join("")}
    ` : "";
    element.querySelectorAll("[data-bomb-code]").forEach((button) => button.addEventListener("click", () => resumeBomb(button.dataset.bombCode)));
  } catch {
    element.innerHTML = "";
  }
}

async function createBomb() {
  try {
    const { bomb } = await api("/bombs", { method: "POST", body: { language: $("#bomb-language").value } });
    $("#bomb-modal").close();
    enterBomb(bomb);
  } catch (error) {
    toast(error.message);
  }
}

async function joinBomb() {
  const code = $("#bomb-join-code").value.trim().toUpperCase();
  if (code.length !== 6) return toast("Digite um código de 6 caracteres");
  if (!state.demo && !isGoogleUser()) {
    state.pendingBombJoinCode = code;
    toast("Faça login com Google para entrar na sala");
    return login();
  }
  try {
    const { bomb } = await api(`/bombs/${code}/join`, { method: "POST", body: {} });
    if ($("#bomb-modal").open) $("#bomb-modal").close();
    enterBomb(bomb);
  } catch (error) {
    toast(error.message);
  }
}

async function resumeBomb(code) {
  try {
    const { bomb } = await api(`/bombs/${code}`);
    $("#bomb-modal").close();
    enterBomb(bomb);
  } catch (error) {
    toast(error.message);
  }
}

function enterBomb(bomb) {
  state.bomb = bomb;
  state.lastBombFeedback = null;
  state.lastBombFinish = null;
  $("#bomb-finish-panel").classList.add("hidden");
  syncRoomClock(bomb);
  subscribeBombTyping();
  renderBomb();
  showScreen("bomb");
  scheduleBombRefresh();
}

async function refreshBomb() {
  if (!state.bomb) return;
  try {
    state.bomb = (await api(`/bombs/${state.bomb.code}`)).bomb;
    syncRoomClock(state.bomb);
    renderBomb();
    scheduleBombRefresh();
  } catch (error) {
    toast(error.message);
  }
}

function scheduleBombRefresh() {
  clearTimeout(state.bombPollTimer);
  if (!state.bomb) return;
  state.bombPollTimer = setTimeout(refreshBomb, document.hidden ? 4000 : 800);
}

function renderBomb() {
  const bomb = state.bomb;
  if (!bomb) return;
  const players = bomb.order.map((uid) => bomb.players[uid]).filter(Boolean);
  const activePlayer = bomb.players[bomb.turn];
  const me = bomb.players[state.user.uid];
  const waiting = bomb.status === "waiting";
  const finished = bomb.status === "finished";
  const canAnswer = bomb.status === "playing" && bomb.turn === state.user.uid;
  $("#bomb-screen").classList.toggle("waiting", waiting);
  $("#bomb-screen").classList.toggle("finished", finished);
  $("#bomb-meta").textContent = `ROOM #${bomb.code} · ${bomb.language === "pt" ? "PORTUGUÊS" : "ENGLISH"} · ${bombLevelLabel(bomb)} · ${bombLevelProgressLabel(bomb)}`;
  $("#bomb-invite-link").textContent = bombInviteUrl();
  $("#bomb-whatsapp-invite").href = `https://wa.me/?text=${encodeURIComponent(`Bora jogar Word Bomb no Poli English Duel? ${bombInviteUrl()}`)}`;
  const playerCard = (player, index) => `
    <div class="bomb-player ${player.uid === bomb.turn ? "active" : ""} ${player.hearts <= 0 ? "out" : ""}">
      <span class="bomb-position">${String(index + 1).padStart(2, "0")}</span>
      <span class="avatar bomb-avatar">${player.photo ? `<img src="${escapeHtml(player.photo)}" alt="">` : "P"}</span>
      <b>${escapeHtml(player.name)}</b>
      <span>${player.score || 0} XP · ${"♥".repeat(player.hearts || 0)}${"♡".repeat(3 - (player.hearts || 0))}</span>
      <em>${player.ready ? "READY" : "WAITING"}</em>
    </div>
  `;
  $("#bomb-lobby-players").classList.toggle("hidden", !waiting);
  $("#bomb-lobby-players").innerHTML = waiting ? `
    <p>// PLAYERS_IN_ROOM</p>
    <div class="bomb-lobby-list">${players.map((player, index) => `
      <div class="bomb-lobby-player">
        <span class="avatar bomb-lobby-avatar">${player.photo ? `<img src="${escapeHtml(player.photo)}" alt="">` : "P"}</span>
        <b>${String(index + 1).padStart(2, "0")} · ${escapeHtml(player.name)}</b>
        <em>${player.ready ? "READY" : "WAITING"}</em>
      </div>
    `).join("")}</div>
  ` : "";
  const turnStage = $(".bomb-turn-stage");
  const compactArena = turnStage.clientWidth < 600;
  const orbitX = compactArena ? 30 : 34;
  const orbitY = compactArena ? 34 : 38;
  $("#bomb-players").innerHTML = players.map((player, index) => {
    const angle = playerAngle(index, players.length);
    const radians = angle * Math.PI / 180;
    return `<div class="bomb-player-slot" style="--player-x:${Math.cos(radians) * orbitX}%;--player-y:${Math.sin(radians) * orbitY}%">${playerCard(player, index)}</div>`;
  }).join("");
  const activeIndex = players.findIndex((player) => player.uid === bomb.turn);
  const activeAngle = playerAngle(activeIndex, players.length);
  const activeRadians = activeAngle * Math.PI / 180;
  const cardInset = (
    Math.abs(Math.cos(activeRadians)) * (compactArena ? 56 : 122)
    + Math.abs(Math.sin(activeRadians)) * (compactArena ? 32 : 42)
  );
  const arrowLength = (
    Math.hypot(
      Math.cos(activeRadians) * turnStage.clientWidth * orbitX / 100,
      Math.sin(activeRadians) * turnStage.clientHeight * orbitY / 100
    )
    - cardInset
  );
  $("#bomb-turn-arrow").style.width = `${Math.max(54, arrowLength)}px`;
  $("#bomb-turn-arrow").style.transform = `rotate(${activeAngle}deg)`;
  $("#bomb-turn-arrow").classList.toggle("hidden", bomb.status !== "playing");
  $("#bomb-phase").textContent = waiting ? "// WAITING_FOR_PLAYERS" : bomb.status === "finished" ? "// GAME_OVER" : `// TURNO_DE_${activePlayer?.name || "PLAYER"}`;
  $("#bomb-prefix").textContent = waiting ? "READY?" : bomb.status === "finished" ? "GG" : bomb.prompt;
  $("#bomb-live-label").textContent = waiting ? "Todos marcam pronto. O host inicia a partida." : `${activePlayer?.name || "PLAYER"} digita uma palavra ao vivo:`;
  $("#bomb-input").disabled = !canAnswer;
  $("#bomb-input").placeholder = canAnswer ? "digite_a_palavra_completa..." : "aguarde_seu_turno...";
  const liveTyping = state.bombTypingByUid[bomb.turn] || {};
  $("#bomb-live-typing").textContent = bomb.status === "playing" && liveTyping.round === bomb.round ? liveTyping.value || "" : "";
  $("#bomb-ready").classList.toggle("hidden", !waiting);
  $("#bomb-invite").classList.toggle("hidden", !waiting);
  $("#bomb-ready").textContent = me?.ready ? "CANCELAR PRONTO" : "ESTOU PRONTO";
  const allReady = players.length >= 2 && players.every((player) => player.ready);
  $("#bomb-start").classList.toggle("hidden", !waiting || bomb.owner !== state.user.uid);
  $("#bomb-start").disabled = !allReady;
  $("#bomb-rematch").classList.toggle("hidden", bomb.status !== "finished");
  if (waiting) $("#bomb-feedback").textContent = allReady ? "Todos prontos. O host já pode iniciar." : "Marque pronto e aguarde os demais jogadores.";
  if (bomb.lastFeedback) renderBombFeedback(bomb.lastFeedback);
  if (bomb.status === "playing") {
    startBombTimer();
    if (canAnswer) focusInput("#bomb-input");
  } else {
    clearInterval(state.bombTimer);
    $("#bomb-screen").classList.remove("danger");
  }
  if (bomb.status === "finished") renderBombFinished();
}

function renderBombFeedback(feedback) {
  const element = $("#bomb-feedback");
  const actor = state.bomb.players[feedback.uid]?.name || "PLAYER";
  const isNewFeedback = feedback.id !== state.lastBombFeedback;
  if (isNewFeedback) state.lastBombFeedback = feedback.id;
  if (feedback.kind === "correct") {
    element.textContent = `${actor} respondeu ${feedback.answer}. +${feedback.xp} XP`;
    element.className = "feedback correct";
    if (isNewFeedback) playSound("correct");
  } else if (feedback.kind === "timeout") {
    element.textContent = `${actor} perdeu um coração: tempo esgotado.`;
    element.className = "feedback timeout";
    if (isNewFeedback) playSound("explosion");
  } else {
    element.textContent = "Palavra inválida. Corrija antes do tempo acabar.";
    element.className = "feedback wrong";
    if (isNewFeedback) playSound("wrong");
  }
}

function playerAngle(index, total) {
  if (index < 0 || total < 1) return 0;
  if (total === 2) return index === 0 ? 180 : 0;
  return -90 + (360 / total) * index;
}

function bombLevelLabel(bomb) {
  return `${(bomb.difficulty || "easy").toUpperCase()} ${bomb.sublevel || 1}`;
}

function bombLevelProgressLabel(bomb) {
  if (bomb.difficulty === "hard" && bomb.sublevel === 3) return "MAX_LEVEL";
  const remaining = Math.max(0, Number(bomb.progression?.nextLevelAt || 0) - Number(bomb.round || 0));
  return `UP_IN_${remaining}_ROUNDS`;
}

function startBombTimer() {
  clearInterval(state.bombTimer);
  const tick = () => {
    if (!state.bomb || state.bomb.status !== "playing") return;
    const remaining = Math.min(ROUND_MS, Math.max(0, Number(state.bomb.deadline) - (Date.now() + state.serverOffset)));
    $("#bomb-timer-bar").style.width = `${(remaining / ROUND_MS) * 100}%`;
    $("#bomb-timer-number").textContent = Math.ceil(remaining / 1000);
    $("#bomb-screen").classList.toggle("danger", remaining > 0 && remaining <= 3000);
    if (remaining <= 0) refreshBomb();
  };
  tick();
  state.bombTimer = setInterval(tick, 160);
}

async function toggleBombReady() {
  try {
    const ready = !state.bomb.players[state.user.uid]?.ready;
    state.bomb = (await api(`/bombs/${state.bomb.code}/ready`, { method: "POST", body: { ready } })).bomb;
    renderBomb();
  } catch (error) {
    toast(error.message);
  }
}

async function startBombMatch() {
  try {
    state.bomb = (await api(`/bombs/${state.bomb.code}/start`, { method: "POST", body: {} })).bomb;
    syncRoomClock(state.bomb);
    await clearBombTyping();
    renderBomb();
  } catch (error) {
    toast(error.message);
  }
}

async function submitBombAnswer(event) {
  event.preventDefault();
  const input = $("#bomb-input");
  const answer = input.value.trim();
  if (!answer || input.disabled) return;
  try {
    state.bomb = (await api(`/bombs/${state.bomb.code}/answer`, { method: "POST", body: { answer, round: state.bomb.round } })).bomb;
    input.value = "";
    await clearBombTyping();
    syncRoomClock(state.bomb);
    renderBomb();
  } catch (error) {
    if (error.payload?.bomb) {
      state.bomb = error.payload.bomb;
      renderBomb();
    }
    $("#bomb-feedback").textContent = error.message;
    $("#bomb-feedback").className = "feedback wrong";
    focusInput("#bomb-input");
  }
}

function bombTypingRootRef() {
  if (!state.database || !state.bomb) return null;
  return state.firebaseDatabase.ref(state.database, `liveBombRooms/${state.bomb.code}/typing`);
}

function subscribeBombTyping() {
  if (state.bombTypingUnsubscribe) state.bombTypingUnsubscribe();
  const reference = bombTypingRootRef();
  if (!reference) return;
  state.bombTypingUnsubscribe = state.firebaseDatabase.onValue(reference, (snapshot) => {
    state.bombTypingByUid = snapshot.val() || {};
    const typing = state.bombTypingByUid[state.bomb?.turn] || {};
    state.bombTypingValue = typing.round === state.bomb?.round ? typing.value || "" : "";
    $("#bomb-live-typing").textContent = state.bombTypingValue;
  });
}

async function publishBombTyping() {
  const root = bombTypingRootRef();
  const reference = root && state.firebaseDatabase.child(root, state.user.uid);
  if (!reference || state.bomb?.turn !== state.user?.uid) return;
  await state.firebaseDatabase.set(reference, {
    uid: state.user.uid,
    value: $("#bomb-input").value.slice(0, 64),
    round: state.bomb.round,
    updatedAt: Date.now()
  });
}

async function clearBombTyping() {
  const root = bombTypingRootRef();
  const reference = root && state.firebaseDatabase.child(root, state.user.uid);
  if (!reference) return;
  try { await state.firebaseDatabase.remove(reference); } catch {}
}

function renderBombFinished() {
  const winner = state.bomb.players[state.bomb.winner];
  const finishKey = `${state.bomb.code}:${state.bomb.winner || "draw"}:${state.bomb.finishReason || "finished"}`;
  $("#bomb-prefix").textContent = "GG";
  $("#bomb-live-typing").textContent = "";
  $("#bomb-input").value = "";
  $("#bomb-feedback").textContent = winner ? `${winner.name} venceu o WORD BOMB!` : "Partida encerrada.";
  $("#bomb-feedback").className = "feedback correct";
  $("#bomb-finish-panel").classList.remove("hidden");
  $("#bomb-finish-title").textContent = winner ? `${winner.name} venceu!` : "Partida encerrada";
  $("#bomb-finish-reason").textContent = winner ? "Último jogador com corações. Vitória registrada no ranking." : "Nenhum jogador permaneceu na arena.";
  $("#bomb-finish-scoreboard").innerHTML = state.bomb.order.map((uid) => state.bomb.players[uid]).filter(Boolean).map((player) => `
    <div><b>${escapeHtml(player.name)}</b><em>${player.score || 0} XP · ${player.hearts || 0} ♥</em></div>
  `).join("");
  if (finishKey !== state.lastBombFinish) {
    state.lastBombFinish = finishKey;
    playSound("victory");
  }
}

async function requestBombRematch() {
  try {
    state.bomb = (await api(`/bombs/${state.bomb.code}/rematch`, { method: "POST", body: {} })).bomb;
    state.lastBombFeedback = null;
    state.lastBombFinish = null;
    $("#bomb-finish-panel").classList.add("hidden");
    await clearBombTyping();
    renderBomb();
    toast("Lobby restaurado. Todos precisam marcar pronto novamente.");
  } catch (error) {
    toast(error.message);
  }
}

async function leaveBomb() {
  const bomb = state.bomb;
  clearTimeout(state.bombPollTimer);
  clearInterval(state.bombTimer);
  if (state.bombTypingUnsubscribe) state.bombTypingUnsubscribe();
  state.bombTypingUnsubscribe = null;
  state.bomb = null;
  $("#bomb-input").value = "";
  $("#bomb-live-typing").textContent = "";
  $("#bomb-screen").classList.remove("danger");
  $("#bomb-screen").classList.remove("waiting", "finished");
  $("#bomb-finish-panel").classList.add("hidden");
  showScreen("home");
  if (bomb) {
    try { await api(`/bombs/${bomb.code}/leave`, { method: "POST", body: {} }); } catch {}
  }
  await loadDashboard();
}

function startRoom(room) {
  state.room = room;
  syncRoomClock(room);
  state.roomCode = room.code;
  state.lastRound = -1;
  state.lastFeedback = null;
  state.pendingRematch = null;
  if ($("#rematch-invite-modal").open) $("#rematch-invite-modal").close();
  renderRoom();
  scheduleRoomRefresh();
}

async function refreshRoom() {
  if (!state.roomCode || state.pollInFlight) return;
  state.pollInFlight = true;
  let keepPolling = true;
  try {
    state.room = (await api(`/rooms/${state.roomCode}`)).room;
    syncRoomClock(state.room);
    renderRoom();
  } catch (error) {
    clearTimeout(state.pollTimer);
    keepPolling = false;
    toast(error.message);
  } finally {
    state.pollInFlight = false;
    if (keepPolling) scheduleRoomRefresh();
  }
}

function scheduleRoomRefresh() {
  clearTimeout(state.pollTimer);
  if (!state.roomCode) return;
  const delay = document.hidden ? 5000 : state.room?.status === "playing" ? 800 : 2500;
  state.pollTimer = setTimeout(refreshRoom, delay);
}

function renderRoom() {
  if (!state.room) return;
  syncRoomClock(state.room);
  if (state.room.status === "waiting") {
    renderLobby();
    showScreen("lobby");
    return;
  }
  renderBattle();
  showScreen("game");
  focusInput("#answer-input");
}

function renderLobby() {
  $("#room-code").textContent = state.roomCode;
  $("#lobby-name").textContent = currentPlayer()?.name || "PLAYER_01";
  renderAvatar($("#lobby-avatar"), currentPlayer(), "P1");
  $("#invite-link").textContent = inviteUrl();
  $("#whatsapp-invite").href = `https://wa.me/?text=${encodeURIComponent(`Bora duelar inglês no Poli English Duel? ${inviteUrl()}`)}`;
}

function renderBattle() {
  const room = state.room;
  const players = Object.values(room.players || {});
  const [one, two = { uid: "waiting", name: "WAITING", hearts: 3, score: 0 }] = players;
  renderFighter("p1", one, "P1");
  renderFighter("p2", two, "P2");
  $("#player-one").classList.toggle("active", room.turn === one.uid);
  $("#player-two").classList.toggle("active", room.turn === two.uid);
  $("#battle-room").textContent = `ROOM #${room.code}`;
  $("#battle-mode").textContent = `${room.mode === "translation" ? "TRANSLATION_RUSH" : "SYLLABLE_STRIKE"} · ${room.difficulty.toUpperCase()} · ${(room.category || "all").toUpperCase()}`;
  const canAnswer = room.turn === state.user.uid && room.status === "playing";
  $("#answer-input").disabled = !canAnswer;
  $("#answer-input").placeholder = canAnswer ? "digite_sua_resposta..." : "aguarde_seu_oponente...";
  $("#turn-label").textContent = room.status === "finished" ? "// GAME_OVER" : canAnswer ? "// SUA_VEZ" : "// VEZ_DO_OPONENTE";
  $("#prompt-hint").textContent = room.prompt?.hint || "BATALHA ENCERRADA";
  $("#prompt-word").textContent = room.prompt?.word || "GG";
  const showedFeedback = renderFeedback(room.lastFeedback);
  if (room.status === "finished") return renderFinished(room);
  if (state.lastRound !== room.round) {
    state.lastRound = room.round;
    if (!showedFeedback) $("#feedback").textContent = canAnswer ? "Sua vez. Capriche!" : "Aguardando resposta...";
    $("#answer-input").value = "";
    if (canAnswer) focusInput("#answer-input");
  }
  startTimer();
}

function renderFinished(room) {
  clearInterval(state.timer);
  const winner = room.players[room.winner];
  const won = room.winner === state.user.uid;
  $("#finish-result").textContent = won ? "YOU_WIN" : room.winner ? "YOU_LOSE" : "DRAW";
  $("#finish-title").textContent = winner ? `${winner.name} venceu!` : "Partida encerrada";
  $("#finish-reason").textContent = room.finishReason === "abandoned"
    ? "Oponente desconectado."
    : room.finishReason === "content_exhausted"
      ? "Todas as palavras inéditas desta seleção foram usadas."
      : "Fim da batalha. XP registrado no ranking.";
  $("#finish-scoreboard").innerHTML = Object.values(room.players).map((player) => `
    <div><b>${escapeHtml(player.name)}</b><em>${player.score || 0} XP · ${player.hearts || 0} ♥</em></div>
  `).join("");
  $("#rematch-button").textContent = room.rematch?.[state.user.uid] ? "AGUARDANDO OPONENTE..." : "PEDIR REVANCHE";
  if (!$("#finish-modal").open) $("#finish-modal").showModal();
  const requester = Object.keys(room.rematch || {}).find((uid) => uid !== state.user.uid);
  if (requester && !room.rematch?.[state.user.uid]) {
    showRematchInvite({ code: room.code, mode: room.mode, requester: room.players[requester].name });
  }
}

function renderFighter(prefix, player, fallback) {
  $(`#${prefix}-name`).textContent = player.name;
  $(`#${prefix}-score`).textContent = `${String(player.score || 0).padStart(3, "0")} XP`;
  $(`#${prefix}-hearts`).textContent = `${"♥ ".repeat(player.hearts || 0)}${"♡ ".repeat(3 - (player.hearts || 0))}`.trim();
  renderAvatar($(`#${prefix}-avatar`), player, fallback);
}

function renderAvatar(element, player, fallback) {
  element.innerHTML = player?.photo ? `<img src="${escapeHtml(player.photo)}" alt="">` : fallback;
  element.classList.remove("tier-beginner", "tier-intermediate", "tier-advanced");
  element.classList.add(`tier-${player?.progression?.tier || "beginner"}`);
  element.title = levelLabel(player?.progression);
}

function levelLabel(progression) {
  const labels = { beginner: "INICIANTE", intermediate: "INTERMEDIÁRIO", advanced: "AVANÇADO" };
  return `${labels[progression?.tier || "beginner"]} ${progression?.level || 1}`;
}

function startTimer() {
  clearInterval(state.timer);
  const tick = () => {
    if (!state.room || state.room.status !== "playing") return;
    const remaining = Math.min(ROUND_MS, Math.max(0, Number(state.room.deadline) - (Date.now() + state.serverOffset)));
    $("#timer-bar").style.width = `${(remaining / ROUND_MS) * 100}%`;
    $("#timer-number").textContent = Math.ceil(remaining / 1000);
    if (remaining <= 0) refreshRoom();
  };
  tick();
  state.timer = setInterval(tick, 160);
}

async function submitAnswer(event) {
  event.preventDefault();
  const input = $("#answer-input");
  const answer = input.value.trim();
  if (!answer || input.disabled) return;
  input.value = "";
  try {
    state.room = (await api(`/rooms/${state.roomCode}/answer`, { method: "POST", body: { answer, round: state.room.round } })).room;
    renderRoom();
  } catch (error) {
    toast(error.message);
  }
}

async function requestRematch() {
  try {
    state.room = (await api(`/rooms/${state.roomCode}/rematch`, { method: "POST", body: { decision: "request" } })).room;
    renderRoom();
    toast("Convite de revanche enviado");
  } catch (error) {
    toast(error.message);
  }
}

function syncRoomClock(room) {
  if (room?.serverNow) state.serverOffset = Number(room.serverNow) - Date.now();
}

async function leaveAndGoHome() {
  const code = state.roomCode;
  clearTimeout(state.pollTimer);
  clearInterval(state.timer);
  state.room = null;
  state.roomCode = null;
  state.lastRound = -1;
  if ($("#finish-modal").open) $("#finish-modal").close();
  showScreen("home");
  if (code) {
    try { await api(`/rooms/${code}/leave`, { method: "POST", body: {} }); } catch {}
  }
  await loadDashboard();
}

async function loadDashboard() {
  try {
    const ranking = await fetch("/api/ranking").then((response) => response.json());
    renderRanking(ranking.ranking);
    if (isGoogleUser()) {
      state.profile = (await api("/profile")).profile;
      renderIdentity();
      renderHistory((await api("/history")).history);
    } else {
      renderHistoryMessage("Faça login para registrar partidas.");
    }
  } catch (error) {
    console.error(error);
  }
}

async function refreshRematches() {
  clearTimeout(state.rematchPollTimer);
  if (!isGoogleUser()) return scheduleRematchRefresh();
  try {
    const { rematches, activeRooms } = await api("/rematches");
    if (!state.roomCode && activeRooms.length) return startRoom(activeRooms[0]);
    if (rematches.length) showRematchInvite(rematches[0]);
  } catch (error) {
    console.error(error);
  }
  scheduleRematchRefresh();
}

function scheduleRematchRefresh() {
  clearTimeout(state.rematchPollTimer);
  state.rematchPollTimer = setTimeout(refreshRematches, document.hidden ? 8000 : 3000);
}

function showRematchInvite(rematch) {
  if (state.pendingRematch?.code === rematch.code && $("#rematch-invite-modal").open) return;
  state.pendingRematch = rematch;
  $("#rematch-invite-text").textContent = `${rematch.requester} quer jogar ${modeLabel(rematch.mode)} novamente.`;
  if (!$("#rematch-invite-modal").open) $("#rematch-invite-modal").showModal();
}

async function acceptRematch() {
  if (!state.pendingRematch) return;
  try {
    const { room } = await api(`/rooms/${state.pendingRematch.code}/rematch`, { method: "POST", body: { decision: "accept" } });
    $("#rematch-invite-modal").close();
    if ($("#finish-modal").open) $("#finish-modal").close();
    startRoom(room);
  } catch (error) {
    toast(error.message);
  }
}

async function declineRematch() {
  if (!state.pendingRematch) return;
  try {
    const { room } = await api(`/rooms/${state.pendingRematch.code}/rematch`, { method: "POST", body: { decision: "decline" } });
    if (state.roomCode === room.code) state.room = room;
    state.pendingRematch = null;
    $("#rematch-invite-modal").close();
    toast("Convite de revanche recusado");
  } catch (error) {
    toast(error.message);
  }
}

function modeLabel(mode) {
  return mode === "translation" ? "Translation Rush" : "Syllable Strike";
}

function renderRanking(ranking) {
  $("#ranking-list").innerHTML = ranking.length ? ranking.map((player, index) => `
    <li><b>#${index + 1}</b><span>${escapeHtml(player.name)} <small>${escapeHtml(levelLabel(player.progression))}</small></span><em>${player.xp} XP</em></li>
  `).join("") : "<li><span>Nenhuma partida registrada ainda.</span></li>";
}

function renderHistory(history) {
  $("#history-list").innerHTML = history.length ? history.map((match) => `
    <li class="${match.result}"><b>${match.result === "win" ? "WIN" : "LOSS"}</b><span>vs ${escapeHtml(match.opponent)}</span><em>${match.xp} XP</em></li>
  `).join("") : "<li><span>Nenhum duelo registrado ainda.</span></li>";
}

function renderHistoryMessage(message) {
  $("#history-list").innerHTML = `<li><span>${escapeHtml(message)}</span></li>`;
}

function isGoogleUser() {
  return Boolean(state.user?.displayName && !state.demo);
}

function requireGoogleLogin() {
  if (state.demo || isGoogleUser()) return true;
  toast("Faça login com Google para jogar");
  return false;
}

function openInvite() {
  const code = new URLSearchParams(location.search).get("room");
  const bombCode = new URLSearchParams(location.search).get("bomb");
  if (code) {
    $("#join-code").value = code.toUpperCase();
    $("#join-modal").showModal();
  }
  if (bombCode) {
    state.pendingBombJoinCode = bombCode.toUpperCase();
    if (isGoogleUser()) completePendingBombJoin();
    else toast("Faça login com Google para entrar diretamente no lobby");
  }
}

async function completePendingJoin() {
  if (!state.pendingJoinCode || !isGoogleUser()) return;
  $("#join-code").value = state.pendingJoinCode;
  state.pendingJoinCode = null;
  await joinRoom();
}

async function completePendingBombJoin() {
  if (!state.pendingBombJoinCode || !isGoogleUser()) return;
  $("#bomb-join-code").value = state.pendingBombJoinCode;
  state.pendingBombJoinCode = null;
  await joinBomb();
}

function inviteUrl() {
  return `${location.origin}${location.pathname}?room=${state.roomCode}`;
}

async function copyCode() {
  await navigator.clipboard.writeText(state.roomCode);
  toast("Código copiado");
}

async function copyInvite() {
  await navigator.clipboard.writeText(inviteUrl());
  toast("Link de convite copiado");
}

function bombInviteUrl() {
  return `${location.origin}${location.pathname}?bomb=${state.bomb?.code || "------"}`;
}

async function copyBombInvite() {
  await navigator.clipboard.writeText(bombInviteUrl());
  toast("Link do Word Bomb copiado");
}

function currentPlayer() {
  return state.room?.players?.[state.user?.uid];
}

function shortName(name) {
  return name.trim().split(/\s+/).slice(0, 2).join("_").toUpperCase();
}

function showScreen(name) {
  Object.entries(screens).forEach(([key, screen]) => screen.classList.toggle("active", key === name));
}

function focusInput(selector) {
  requestAnimationFrame(() => {
    const input = $(selector);
    if (input && !input.disabled) input.focus();
  });
}

function renderFeedback(feedback) {
  if (!feedback || feedback.id === state.lastFeedback) return false;
  state.lastFeedback = feedback.id;
  const ownAction = feedback.uid === state.user.uid;
  const messages = {
    correct: ownAction ? `Correto! +${feedback.xp} XP` : "Oponente acertou. +100 XP",
    wrong: ownAction ? `Ops! Resposta: ${feedback.answer}` : `Oponente errou. Resposta: ${feedback.answer}`,
    timeout: ownAction ? `Tempo esgotado! Resposta: ${feedback.answer}` : `Tempo do oponente esgotado. Resposta: ${feedback.answer}`
  };
  const element = $("#feedback");
  element.textContent = messages[feedback.kind];
  element.className = `feedback ${feedback.kind}`;
  const players = Object.values(state.room.players);
  const index = players.findIndex((player) => player.uid === feedback.uid);
  const fighter = $(`#player-${index === 0 ? "one" : "two"}`);
  fighter.classList.remove("hit", "gain");
  void fighter.offsetWidth;
  fighter.classList.add(feedback.kind === "correct" ? "gain" : "hit");
  playSound(feedback.kind === "correct" ? "gain" : "hit");
  return true;
}

function toggleMute() {
  state.muted = !state.muted;
  localStorage.setItem("poli-muted", state.muted);
  renderMute();
  if (state.muted) stopMusic();
  else {
    playSound("gain");
    startMusic();
  }
}

function renderMute() {
  $("#mute-button").textContent = state.muted ? "mute()" : "sound_on()";
}

function changeMusicTrack(event) {
  state.musicTrack = event.target.value;
  localStorage.setItem("poli-music-track", state.musicTrack);
  stopMusic();
  startMusic();
}

function getAudioContext() {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return null;
  if (!state.audioContext) state.audioContext = new AudioContext();
  if (state.audioContext.state === "suspended") state.audioContext.resume();
  return state.audioContext;
}

function startMusic() {
  if (state.muted || state.musicTrack === "off" || state.musicTimer) return;
  const melodies = {
    lounge_01: [261.63, 329.63, 392, 493.88, 392, 329.63, 293.66, 349.23],
    lounge_02: [220, 277.18, 329.63, 415.3, 369.99, 329.63, 246.94, 293.66]
  };
  const playNote = () => {
    const notes = melodies[state.musicTrack];
    const context = getAudioContext();
    if (!notes || !context) return;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.value = notes[state.musicStep++ % notes.length];
    oscillator.type = "sine";
    gain.gain.setValueAtTime(.025, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, context.currentTime + .62);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + .64);
  };
  playNote();
  state.musicTimer = setInterval(playNote, 720);
}

function stopMusic() {
  clearInterval(state.musicTimer);
  state.musicTimer = null;
  state.musicStep = 0;
}

function playSound(kind) {
  if (state.muted) return;
  const context = getAudioContext();
  if (!context) return;
  const note = (frequency, delay, duration, type = "square", volume = .055) => {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const start = context.currentTime + delay;
    oscillator.frequency.value = frequency;
    oscillator.type = type;
    gain.gain.setValueAtTime(volume, start);
    gain.gain.exponentialRampToValueAtTime(.001, start + duration);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + duration);
  };
  if (kind === "explosion") {
    const duration = .48;
    const buffer = context.createBuffer(1, context.sampleRate * duration, context.sampleRate);
    const data = buffer.getChannelData(0);
    for (let index = 0; index < data.length; index += 1) data[index] = (Math.random() * 2 - 1) * (1 - index / data.length);
    const source = context.createBufferSource();
    const gain = context.createGain();
    source.buffer = buffer;
    gain.gain.setValueAtTime(.18, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, context.currentTime + duration);
    source.connect(gain);
    gain.connect(context.destination);
    source.start();
    note(92, 0, .4, "sawtooth", .09);
    return;
  }
  if (kind === "correct" || kind === "gain") {
    note(523.25, 0, .12);
    note(659.25, .08, .14);
    note(783.99, .16, .18);
    return;
  }
  if (kind === "victory") {
    note(523.25, 0, .35, "triangle", .07);
    note(659.25, .1, .38, "triangle", .07);
    note(783.99, .2, .5, "triangle", .08);
    return;
  }
  note(180, 0, .18, "sawtooth", .07);
  note(120, .08, .22, "square", .055);
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  setTimeout(() => element.classList.remove("show"), 2400);
}

function notifyLeaveOnUnload() {
  if (state.bomb && state.apiToken) {
    fetch(`/api/bombs/${state.bomb.code}/leave`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.apiToken}` },
      body: "{}",
      keepalive: true
    });
  }
  if (!state.roomCode || !state.apiToken) return;
  fetch(`/api/rooms/${state.roomCode}/leave`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.apiToken}` },
    body: "{}",
    keepalive: true
  });
}

function escapeHtml(value = "") {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[character]);
}
