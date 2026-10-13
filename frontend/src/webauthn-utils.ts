/**
 * WebAuthn/FIDO2 utilities for passkey registration and authentication.
 * Handles browser WebAuthn API calls and challenge verification.
 */

/**
 * Convert ArrayBuffer to base64url string
 */
export function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

/**
 * Convert base64url string to ArrayBuffer
 */
export function base64UrlToArrayBuffer(base64Url: string): ArrayBuffer {
  const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
  const padLen = (4 - (base64.length % 4)) % 4
  const padded = base64 + '='.repeat(padLen)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer
}

/**
 * Start passkey registration
 */
export async function startRegistration(
  token: string,
  credentialName: string,
  rpId: string,
  rpName: string,
  userId: string,
  username: string
): Promise<{
  challenge: string
  credential_id: string
  name: string
}> {
  // Get registration options from backend
  const beginRes = await fetch('/api/auth/webauthn/register-begin', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      username,
      credential_name: credentialName,
    }),
  })

  if (!beginRes.ok) {
    throw new Error(`Registration setup failed: ${beginRes.statusText}`)
  }

  const options = await beginRes.json() as {
    challenge: string
    rp_id: string
    rp_name: string
    user_id: string
    username: string
    display_name: string
  }

  // Convert to WebAuthn format
  const createOptions: CredentialCreationOptions = {
    publicKey: {
      challenge: base64UrlToArrayBuffer(options.challenge),
      rp: {
        name: options.rp_name,
        id: options.rp_id,
      },
      user: {
        id: base64UrlToArrayBuffer(options.user_id),
        name: options.username,
        displayName: options.display_name,
      },
      pubKeyCredParams: [
        { alg: -7, type: 'public-key' }, // ES256
        { alg: -257, type: 'public-key' }, // RS256
      ],
      attestation: 'direct',
      timeout: 60000,
      authenticatorSelection: {
        authenticatorAttachment: 'platform',
        userVerification: 'preferred',
        residentKey: 'preferred',
      },
    },
  }

  // Call WebAuthn API
  const credential = await navigator.credentials.create(createOptions) as PublicKeyCredential | null

  if (!credential) {
    throw new Error('Registration was cancelled')
  }

  // Send to backend for verification
  const response = credential.response as AuthenticatorAttestationResponse
  const completeRes = await fetch('/api/auth/webauthn/register-complete', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      id: credential.id,
      raw_id: arrayBufferToBase64Url(credential.rawId),
      response: {
        client_data_json: arrayBufferToBase64Url(response.clientDataJSON),
        attestation_object: arrayBufferToBase64Url(response.attestationObject),
        public_key: 'extracted-from-attestation', // Would be extracted properly in production
      },
      type: credential.type,
    }),
  })

  if (!completeRes.ok) {
    throw new Error(`Registration verification failed: ${completeRes.statusText}`)
  }

  return completeRes.json()
}

/**
 * Start passkey authentication
 */
export async function startAuthentication(rpId: string): Promise<{
  access_token: string
  refresh_token: string
  token_type: string
}> {
  // Get authentication options from backend
  const beginRes = await fetch('/api/auth/webauthn/authenticate-begin', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  })

  if (!beginRes.ok) {
    throw new Error(`Authentication setup failed: ${beginRes.statusText}`)
  }

  const options = await beginRes.json() as {
    challenge: string
    rp_id: string
    user_verification: string
  }

  // Convert to WebAuthn format
  const getOptions: CredentialRequestOptions = {
    publicKey: {
      challenge: base64UrlToArrayBuffer(options.challenge),
      rpId: options.rp_id,
      userVerification: (options.user_verification || 'preferred') as UserVerificationRequirement,
      timeout: 60000,
    },
  }

  // Call WebAuthn API
  const assertion = await navigator.credentials.get(getOptions) as PublicKeyCredential | null

  if (!assertion) {
    throw new Error('Authentication was cancelled')
  }

  // Send to backend for verification
  const response = assertion.response as AuthenticatorAssertionResponse
  const completeRes = await fetch('/api/auth/webauthn/authenticate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      id: assertion.id,
      raw_id: arrayBufferToBase64Url(assertion.rawId),
      response: {
        client_data_json: arrayBufferToBase64Url(response.clientDataJSON),
        authenticator_data: arrayBufferToBase64Url(response.authenticatorData),
        signature: arrayBufferToBase64Url(response.signature),
        user_handle: response.userHandle ? arrayBufferToBase64Url(response.userHandle) : null,
      },
      type: assertion.type,
    }),
  })

  if (!completeRes.ok) {
    throw new Error(`Authentication verification failed: ${completeRes.statusText}`)
  }

  return completeRes.json()
}

/**
 * Check if WebAuthn is supported in the browser
 */
export function isWebAuthnSupported(): boolean {
  if (typeof window === 'undefined') return false
  if (!window.PublicKeyCredential) return false
  if (!navigator.credentials) return false
  return typeof navigator.credentials.create === 'function' &&
         typeof navigator.credentials.get === 'function'
}

/**
 * Check if platform authenticator is available (Face ID, Touch ID, Windows Hello, etc.)
 * TODO: Implement with proper TypeScript handling for PublicKeyCredential API
 */
export async function isPlatformAuthenticatorAvailable(): Promise<boolean> {
  // Placeholder - not used in current implementation
  return false
}
