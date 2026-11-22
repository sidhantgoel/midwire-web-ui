export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Called when the server says the session is gone, so the app can show the
// login page instead of a page full of errors.
let onLoggedOut: () => void = () => {};
export function setLoggedOutHandler(handler: () => void): void {
  onLoggedOut = handler;
}

function describe(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: one entry per bad field.
    return detail.map((d: { msg?: string }) => d.msg ?? "invalid value").join("; ");
  }
  return `Request failed (${status}).`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      // The backend rejects writes without this header (CSRF protection).
      headers: { "X-Midwire": "1", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach Midwire. Check the network connection.");
  }
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // Not every answer has a JSON body.
  }
  if (!response.ok) {
    const message = describe(data, response.status);
    if (response.status === 401 && (message === "login_required" || message === "setup_required")) {
      onLoggedOut();
      throw new ApiError(401, "Please log in again.");
    }
    throw new ApiError(response.status, message);
  }
  return data as T;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T,>(path: string, body?: unknown) => request<T>("PUT", path, body),
  delete: <T,>(path: string) => request<T>("DELETE", path),
};

export function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
