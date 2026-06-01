const config = window.POLI_FIREBASE_CONFIG || {};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  auth: null,
  firebase: null,
  user: null,
  room: null,
  roomCode: null,
  pollTimer: null,
  pollInFlight: false,
  timer: null,
  selectedMode: "translation",
  selectedDifficulty: "easy",
  lastRound: -1,
  apiToken: null,
  demo: !config.apiKey || new URLSearchParams(location.search).has("demo")
};

const screens = {
  home: $("#home-screen"),
  lobby: $("#lobby-screen"),
  game: $("#game-screen")
};

boot();

async function boot() {
  bindInterface();
  await connectFirebase();
  renderIdentity();
  await loadDashboard();
  openInvite();
}

function bindInterface() {
  $$("[data-open-modal]").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.mode) selectMode(button.dataset.mode);
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
  $("#rematch-button").addEventListener("click", requestRematch);
  $("#finish-home").addEventListener("click", leaveAndGoHome);
  window.addEventListener("beforeunload", notifyLeaveOnUnload);
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
    const app = appSdk.initializeApp(config);
    state.firebase = authSdk;
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
    state.demo = true;
    state.user = { uid: `demo-${Date.now()}`, displayName: "Demo Player", photoURL: "" };
    $("#connection-label").textContent = "demo local";
    toast("Firebase indisponível: modo demo ativado");
  }
}

async function login() {
  if (state.demo) return toast("Modo demo ativo");
  try {
    await state.firebase.signInWithPopup(state.auth, new state.firebase.GoogleAuthProvider());
    state.user = state.auth.currentUser;
    renderIdentity();
    await loadDashboard();
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
    await state.firebase.signOut(state.auth);
    state.user = null;
    renderIdentity();
    renderHistoryMessage("Faça login para registrar partidas.");
    toast("Logout realizado");
  } catch (error) {
    console.error(error);
    toast("Não foi possível sair");
  }
}

async function ensureUser() {
  if (state.user) return state.user;
  if (state.demo) return state.user;
  try {
    state.user = (await state.firebase.signInAnonymously(state.auth)).user;
    return state.user;
  } catch (error) {
    toast("Entre com Google para jogar");
    throw error;
  }
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
  if (!response.ok) throw new Error(payload.error || "Falha na operação");
  return payload;
}

function renderIdentity() {
  const loggedWithGoogle = state.user?.displayName && !state.demo;
  $("#user-label").textContent = loggedWithGoogle ? shortName(state.user.displayName) : "";
  $("#auth-button").textContent = loggedWithGoogle ? "logout()" : "login_google()";
}

function selectMode(mode) {
  state.selectedMode = mode;
  $$(".mode-choice").forEach((button) => button.classList.toggle("selected", button.dataset.choice === mode));
}

function selectDifficulty(difficulty) {
  state.selectedDifficulty = difficulty;
  $$(".difficulty-choice").forEach((button) => button.classList.toggle("selected", button.dataset.difficulty === difficulty));
}

async function createRoom() {
  try {
    const { room } = await api("/rooms", { method: "POST", body: { mode: state.selectedMode, difficulty: state.selectedDifficulty, demo: state.demo } });
    $("#create-modal").close();
    startRoom(room);
  } catch (error) {
    toast(error.message);
  }
}

async function joinRoom() {
  const code = $("#join-code").value.trim().toUpperCase();
  if (code.length !== 6) return toast("Digite um código de 6 caracteres");
  try {
    const { room } = await api(`/rooms/${code}/join`, { method: "POST", body: {} });
    $("#join-modal").close();
    startRoom(room);
  } catch (error) {
    toast(error.message);
  }
}

function startRoom(room) {
  state.room = room;
  state.roomCode = room.code;
  state.lastRound = -1;
  renderRoom();
  scheduleRoomRefresh();
}

async function refreshRoom() {
  if (!state.roomCode || state.pollInFlight) return;
  state.pollInFlight = true;
  let keepPolling = true;
  try {
    state.room = (await api(`/rooms/${state.roomCode}`)).room;
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
  if (state.room.status === "waiting") {
    renderLobby();
    showScreen("lobby");
    return;
  }
  renderBattle();
  showScreen("game");
}

function renderLobby() {
  $("#room-code").textContent = state.roomCode;
  $("#lobby-name").textContent = currentPlayer()?.name || "PLAYER_01";
  renderAvatar($("#lobby-avatar"), currentPlayer(), "P1");
  $("#invite-link").textContent = inviteUrl();
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
  $("#battle-mode").textContent = `${room.mode === "translation" ? "TRANSLATION_RUSH" : "SYLLABLE_STRIKE"} · ${room.difficulty.toUpperCase()}`;
  const canAnswer = room.turn === state.user.uid && room.status === "playing";
  $("#answer-input").disabled = !canAnswer;
  $("#answer-input").placeholder = canAnswer ? "digite_sua_resposta..." : "aguarde_seu_oponente...";
  $("#turn-label").textContent = room.status === "finished" ? "// GAME_OVER" : canAnswer ? "// SUA_VEZ" : "// VEZ_DO_OPONENTE";
  $("#prompt-hint").textContent = room.prompt?.hint || "BATALHA ENCERRADA";
  $("#prompt-word").textContent = room.prompt?.word || "GG";
  if (room.status === "finished") return renderFinished(room);
  if (state.lastRound !== room.round) {
    state.lastRound = room.round;
    $("#feedback").textContent = canAnswer ? "Sua vez. Capriche!" : "Aguardando resposta...";
    $("#answer-input").value = "";
    if (canAnswer) $("#answer-input").focus();
  }
  startTimer();
}

function renderFinished(room) {
  clearInterval(state.timer);
  const winner = room.players[room.winner];
  const won = room.winner === state.user.uid;
  $("#finish-result").textContent = won ? "YOU_WIN" : room.winner ? "YOU_LOSE" : "DRAW";
  $("#finish-title").textContent = winner ? `${winner.name} venceu!` : "Partida encerrada";
  $("#finish-reason").textContent = room.finishReason === "abandoned" ? "Oponente desconectado." : "Fim da batalha. XP registrado no ranking.";
  $("#rematch-button").textContent = room.rematch?.[state.user.uid] ? "AGUARDANDO OPONENTE..." : "PEDIR REVANCHE";
  if (!$("#finish-modal").open) $("#finish-modal").showModal();
}

function renderFighter(prefix, player, fallback) {
  $(`#${prefix}-name`).textContent = player.name;
  $(`#${prefix}-score`).textContent = `${String(player.score || 0).padStart(3, "0")} XP`;
  $(`#${prefix}-hearts`).textContent = `${"♥ ".repeat(player.hearts || 0)}${"♡ ".repeat(3 - (player.hearts || 0))}`.trim();
  renderAvatar($(`#${prefix}-avatar`), player, fallback);
}

function renderAvatar(element, player, fallback) {
  element.innerHTML = player?.photo ? `<img src="${escapeHtml(player.photo)}" alt="">` : fallback;
}

function startTimer() {
  clearInterval(state.timer);
  const tick = () => {
    if (!state.room || state.room.status !== "playing") return;
    const remaining = Math.max(0, state.room.deadline - Date.now());
    $("#timer-bar").style.width = `${(remaining / 10000) * 100}%`;
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
    state.room = (await api(`/rooms/${state.roomCode}/rematch`, { method: "POST", body: {} })).room;
    $("#finish-modal").close();
    renderRoom();
  } catch (error) {
    toast(error.message);
  }
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
      renderHistory((await api("/history")).history);
    } else {
      renderHistoryMessage("Faça login para registrar partidas.");
    }
  } catch (error) {
    console.error(error);
  }
}

function renderRanking(ranking) {
  $("#ranking-list").innerHTML = ranking.length ? ranking.map((player, index) => `
    <li><b>#${index + 1}</b><span>${escapeHtml(player.name)}</span><em>${player.xp} XP</em></li>
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

function openInvite() {
  const code = new URLSearchParams(location.search).get("room");
  if (!code) return;
  $("#join-code").value = code.toUpperCase();
  $("#join-modal").showModal();
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

function currentPlayer() {
  return state.room?.players?.[state.user?.uid];
}

function shortName(name) {
  return name.trim().split(/\s+/).slice(0, 2).join("_").toUpperCase();
}

function showScreen(name) {
  Object.entries(screens).forEach(([key, screen]) => screen.classList.toggle("active", key === name));
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  setTimeout(() => element.classList.remove("show"), 2400);
}

function notifyLeaveOnUnload() {
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
