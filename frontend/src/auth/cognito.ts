// Cognito SRP authentication (no client secret) via amazon-cognito-identity-js.
import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserPool,
  CognitoUserSession,
} from "amazon-cognito-identity-js";
import { config } from "../config";

const pool = new CognitoUserPool({
  UserPoolId: config.userPoolId,
  ClientId: config.userPoolClientId,
});

export function signIn(email: string, password: string): Promise<CognitoUserSession> {
  const user = new CognitoUser({ Username: email, Pool: pool });
  const details = new AuthenticationDetails({ Username: email, Password: password });
  return new Promise((resolve, reject) => {
    user.authenticateUser(details, {
      onSuccess: resolve,
      onFailure: reject,
      // New-password challenges are out of scope for the demo; surface as an error.
      newPasswordRequired: () => reject(new Error("비밀번호 변경이 필요합니다. 관리자에게 문의하세요.")),
    });
  });
}

// AgentCore rejects a token that expires "within the next minute" (Ineffectual token).
// getSession only refreshes a FULLY expired token, so we proactively refresh when the access
// token is within this buffer of expiry.
const REFRESH_BUFFER_SEC = 300; // 5 min

function isNearExpiry(session: CognitoUserSession): boolean {
  const exp = session.getAccessToken().getExpiration(); // epoch seconds
  return exp - Math.floor(Date.now() / 1000) < REFRESH_BUFFER_SEC;
}

export function currentSession(): Promise<CognitoUserSession | null> {
  const user = pool.getCurrentUser();
  if (!user) return Promise.resolve(null);
  return new Promise((resolve) => {
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session) return resolve(null);
      if (!isNearExpiry(session)) return resolve(session);
      // near expiry → force a refresh with the refresh token
      user.refreshSession(session.getRefreshToken(), (rErr, fresh) => {
        resolve(rErr ? session : fresh); // fall back to the current session if refresh fails
      });
    });
  });
}

export function signOut(): void {
  pool.getCurrentUser()?.signOut();
}

// AgentCore's JWT authorizer matches the access token's client_id claim — use the ACCESS
// token (not the ID token, whose audience claim is shaped differently).
export function accessToken(session: CognitoUserSession): string {
  return session.getAccessToken().getJwtToken();
}

export function emailFrom(session: CognitoUserSession): string {
  return (session.getIdToken().payload.email as string) ?? "";
}

// RBAC (ADR-001): the prompt-admin Cognito group. UI gating only — the backend independently
// re-checks cognito:groups on the verified bearer and is authoritative.
const ADMIN_GROUP = "admin";

export function groupsFrom(session: CognitoUserSession): string[] {
  const g = session.getIdToken().payload["cognito:groups"];
  return Array.isArray(g) ? (g as string[]) : g ? [String(g)] : [];
}

export function isAdmin(session: CognitoUserSession): boolean {
  return groupsFrom(session).includes(ADMIN_GROUP);
}
