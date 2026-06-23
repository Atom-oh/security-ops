// INTENTIONALLY VULNERABLE — FSI-Mythos scanner testbed (defensive corpus).
// CWE-79: DOM-based cross-site scripting.
export function renderBalance(el, balanceFromQuery) {
  // Untrusted value written as HTML → script injection.
  el.innerHTML = "<span>" + balanceFromQuery + "</span>"; // CWE-79
}
