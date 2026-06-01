const config = window.POLI_FIREBASE_CONFIG || {};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  auth: null,
  firebase: null,
  user: null,
  profile: null,
  room: null,
  roomCode: null,
  context: null,
  contextPollTimer: null,
  pollTimer: null,
  pollInFlight: false,
  timer: null,
  selectedMode: "translation",
  selectedDifficulty: "easy",
  selectedCategory: "all",
  lastRound: -1,
  lastFeedback: null,
  muted: localStorage.getItem("poli-muted") === "true",
  apiToken: null,
  demo: !config.apiKey || new URLSearchParams(location.search).has("demo")
};

const screens = {
  home: $("#home-screen"),
  lobby: $("#lobby-screen"),
  game: $("#game-screen"),
  context: $("#context-screen")
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
  $("#rematch-button").addEventListener("click", requestRematch);
  $("#finish-home").addEventListener("click", leaveAndGoHome);
  $("#open-context").addEventListener("click", openContextModal);
  $("#start-context").addEventListener("click", startContext);
  $("#join-context").addEventListener("click", joinContext);
  $("#leave-context").addEventListener("click", leaveContext);
  $("#context-form").addEventListener("submit", submitContextWord);
  window.addEventListener("beforeunload", notifyLeaveOnUnload);
  renderMute();
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
  if (!response.ok) throw new Error(payload.error || "Falha na operação");
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

function startRoom(room) {
  state.room = room;
  state.roomCode = room.code;
  state.lastRound = -1;
  state.lastFeedback = null;
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
    const remaining = Math.max(0, state.room.deadline - Date.now());
    $("#timer-bar").style.width = `${(remaining / 10000) * 100}%`;
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
  if (!code) return;
  if (!requireGoogleLogin()) return;
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
  if (!state.muted) playSound("gain");
}

function renderMute() {
  $("#mute-button").textContent = state.muted ? "mute()" : "sound_on()";
}

function playSound(kind) {
  if (state.muted) return;
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return;
  const context = new AudioContext();
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.frequency.value = kind === "gain" ? 660 : 160;
  oscillator.type = "square";
  gain.gain.setValueAtTime(.06, context.currentTime);
  gain.gain.exponentialRampToValueAtTime(.001, context.currentTime + .16);
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start();
  oscillator.stop(context.currentTime + .16);
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
