import type { Connection, Transport } from "./api";

/**
 * The two path vocabularies a NAS has, and how to move a path between them.
 *
 * Every folder on a device has two names: the FTP server's (`/public/TV Shows`)
 * and the real filesystem's (`/mnt/md0/public/TV Shows`). The FTP server is
 * rooted at the device's filesystem root, so the two differ by exactly that
 * prefix. Which name a path must be written in depends on the transport, not on
 * the folder - so a path that is right for an FTP job is wrong for the same
 * folder over rsync, and rsync rejects it rather than guessing.
 *
 * (`root_path` plays no part: it is where FTP browsing *starts*, not an offset
 * into the FTP namespace.)
 */

function norm(path: string): string {
  const parts: string[] = [];
  for (const segment of (path || "/").split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") parts.pop();
    else parts.push(segment);
  }
  return "/" + parts.join("/");
}

function within(path: string, root: string): boolean {
  return root === "/" || path === root || path.startsWith(root + "/");
}

/** Where a pane should start for a given transport. */
export function rootFor(conn: Connection | undefined, transport: Transport): string {
  if (!conn) return "/";
  return transport === "rsync" ? conn.fs_root || "/" : conn.root_path || "/";
}

/**
 * The same folder, named the way `to` names it.
 *
 * Returns the path unchanged when there is nothing to translate: the connection
 * is unknown, it has no filesystem root configured, or the path already reads as
 * a `to` path. Leaving a path alone beats resetting it to a root - the user can
 * see what they picked and fix it, and the backend now names the path it wanted.
 */
export function retargetPath(
  conn: Connection | undefined,
  from: Transport,
  to: Transport,
  path: string
): string {
  if (!conn || from === to) return path;
  const fsRoot = norm(conn.fs_root || "/");
  if (fsRoot === "/") return path;

  const target = norm(path);
  if (to === "rsync") {
    return within(target, fsRoot) ? path : norm(fsRoot + target);
  }
  return within(target, fsRoot) ? norm(target.slice(fsRoot.length) || "/") : path;
}
