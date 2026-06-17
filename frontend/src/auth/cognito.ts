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

export function currentSession(): Promise<CognitoUserSession | null> {
  const user = pool.getCurrentUser();
  if (!user) return Promise.resolve(null);
  return new Promise((resolve) => {
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      resolve(err ? null : session);
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
