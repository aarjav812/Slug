// Use environment variable or default to localhost:5000
// In production, set VITE_API_URL to your Vercel backend URL
const API = import.meta.env.VITE_API_URL || "http://localhost:5000";
const IS_DEV = API.includes("localhost");

function handleFetchError(error) {
  if (error.message.includes('fetch') || error.name === 'TypeError') {
    const msg = IS_DEV 
      ? 'Cannot connect to server. Make sure the backend is running on http://localhost:5000'
      : `Cannot connect to backend at ${API}`;
    throw new Error(msg);
  }
  throw error;
}

export async function createReport(formData) {
  try {
    const r = await fetch(`${API}/api/v1/reports`, {
      method: "POST",
      body: formData
      // Note: Do NOT set Content-Type header when sending FormData
      // Browser will automatically set it with the correct boundary
    });
    if (!r.ok) {
      // Try to get error details from response
      const errText = await r.text();
      throw new Error(`Create failed: ${r.status} - ${errText}`);
    }
    return r.json();
  } catch (error) {
    handleFetchError(error);
  }
}

export async function fetchReport(ticket, code) {
  try {
    const r = await fetch(`${API}/api/v1/reports/${ticket}?code=${encodeURIComponent(code)}`);
    if (!r.ok) throw new Error(`Fetch failed: ${r.status}`);
    return r.json();
  } catch (error) {
    handleFetchError(error);
  }
}

export async function postMessage(ticket, code, body) {
  try {
    const r = await fetch(`${API}/api/v1/reports/${ticket}/messages?code=${encodeURIComponent(code)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body })
    });
    if (!r.ok) throw new Error(`Message failed: ${r.status}`);
    return r.json();
  } catch (error) {
    handleFetchError(error);
  }
}

export async function fetchPublicReports(page = 1, perPage = 20) {
  try {
    const r = await fetch(`${API}/api/v1/reports/public?page=${page}&per_page=${perPage}`);
    if (!r.ok) throw new Error(`Fetch reports failed: ${r.status}`);
    return r.json();
  } catch (error) {
    handleFetchError(error);
  }
}

export async function likeReport(reportId, email) {
  try {
    const r = await fetch(`${API}/api/v1/reports/${reportId}/like`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email })
    });
    if (!r.ok) throw new Error(`Like failed: ${r.status}`);
    return r.json();
  } catch (error) {
    handleFetchError(error);
  }
}

export async function addReportComment(reportId, email, name, body) {
  try {
    const r = await fetch(`${API}/api/v1/reports/${reportId}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, name, body })
    });
    if (!r.ok) throw new Error(`Comment failed: ${r.status}`);
    return r.json();
  } catch (error) {
    handleFetchError(error);
  }
}

export async function getReportComments(reportId) {
  try {
    const r = await fetch(`${API}/api/v1/reports/${reportId}/comments`);
    if (!r.ok) throw new Error(`Fetch comments failed: ${r.status}`);
    return r.json();
  } catch (error) {
    handleFetchError(error);
  }
}