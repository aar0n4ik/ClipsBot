const b64d = (s: string): Uint8Array => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const b64e = (u8: Uint8Array): string => {
  let s = "";
  u8.forEach(b => (s += String.fromCharCode(b)));
  return btoa(s);
};

export async function keyFrom(
  password: string,
  salt: Uint8Array,
  iter: number,
  usage: "encrypt" | "decrypt"
): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: salt as BufferSource, iterations: iter, hash: "SHA-256" },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    [usage]
  );
}

export async function decrypt<T = any>(
  env: { salt: string; iter: number; iv: string; ct: string },
  password: string
): Promise<T> {
  const key = await keyFrom(password, b64d(env.salt), env.iter, "decrypt");
  const decrypted = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: b64d(env.iv) as BufferSource },
    key,
    b64d(env.ct) as BufferSource
  );
  return JSON.parse(new TextDecoder().decode(decrypted));
}

export async function encrypt(obj: any, password: string): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const iter = 600000;
  const key = await keyFrom(password, salt, iter, "encrypt");
  const ct = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      key,
      new TextEncoder().encode(JSON.stringify(obj))
    )
  );
  return JSON.stringify({
    v: 1,
    iter,
    salt: b64e(salt),
    iv: b64e(iv),
    ct: b64e(ct),
  });
}
