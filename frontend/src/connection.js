const STORAGE_KEY = "ggg_connection_id";

export function getConnectionId() {
  let id = sessionStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}

export function getStoredPlayerId() {
  return localStorage.getItem("ggg_player_id") || "";
}

export function setStoredPlayerId(id) {
  localStorage.setItem("ggg_player_id", id);
}
