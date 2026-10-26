/**
 * Notification helpers and activity log UI component.
 */
import { escapeHtml } from "./cards.js";
import { on } from "./events.js";

/**
 * Appends a notification item to the notifications-list container.
 * Keeps at most 5 latest items in the activity log.
 */
export function addNotification(message: string, type: "info" | "success" | "error" | string = "info"): void {
  const list = document.getElementById("notifications-list");
  if (!list) return;

  // Remove empty placeholder
  const empty = list.querySelector(".empty");
  if (empty) {
    empty.remove();
  }

  const timeStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const item = document.createElement("div");
  item.className = `notification-item ${type}`;
  item.innerHTML = `
        <div>${escapeHtml(message)}</div>
        <span class="notification-time">${escapeHtml(timeStr)}</span>
    `;

  list.insertBefore(item, list.firstChild);

  while (list.childNodes.length > 5) {
    if (list.lastChild) {
      list.removeChild(list.lastChild);
    }
  }
}

// Automatically subscribe to the global notify event
on("notify", (message: string, type?: string) => {
  addNotification(message, type || "info");
});
