/** 账号：3~20 字符，除表情等特殊字符外 */
export const ACCOUNT_MIN = 3;
export const ACCOUNT_MAX = 20;

/** 登录密码校验：3~20 位（兼容历史短密码） */
export const PASSWORD_MIN = 3;
/** 注册密码校验：6~20 位 */
export const PASSWORD_REGISTER_MIN = 6;
export const PASSWORD_MAX = 20;

const EMOJI_RE = /(\p{Extended_Pictographic}|\p{Emoji_Presentation})/u;
const INVISIBLE_RE = /[\s\x00-\x1F\x7F]/;

export function sanitizeAccountInput(value: string): string {
  return value.replace(EMOJI_RE, '').slice(0, ACCOUNT_MAX);
}

export function sanitizePasswordInput(value: string): string {
  return value.replace(EMOJI_RE, '').slice(0, PASSWORD_MAX);
}

export function validateAccount(account: string): string | null {
  if (!account) return '请输入账号';
  if (account.length < ACCOUNT_MIN || account.length > ACCOUNT_MAX) {
    return `账号长度为 ${ACCOUNT_MIN}~${ACCOUNT_MAX} 个字符`;
  }
  if (EMOJI_RE.test(account)) return '账号不能包含表情等特殊字符';
  if (INVISIBLE_RE.test(account)) return '账号不能包含空格或不可见字符';
  return null;
}

/** 登录密码：3~20 位 */
export function validatePassword(password: string): string | null {
  if (!password) return '请输入密码';
  if (password.length < PASSWORD_MIN || password.length > PASSWORD_MAX) {
    return `密码长度为 ${PASSWORD_MIN}~${PASSWORD_MAX} 位`;
  }
  if (EMOJI_RE.test(password)) return '密码不能包含表情';
  return null;
}

/** 注册密码：6~20 位 */
export function validateRegisterPassword(password: string): string | null {
  if (!password) return '请输入密码';
  if (password.length < PASSWORD_REGISTER_MIN || password.length > PASSWORD_MAX) {
    return `密码长度为 ${PASSWORD_REGISTER_MIN}~${PASSWORD_MAX} 位`;
  }
  if (EMOJI_RE.test(password)) return '密码不能包含表情';
  return null;
}

export function isAccountValid(account: string): boolean {
  return validateAccount(account) === null;
}

export function isPasswordValid(password: string): boolean {
  return validatePassword(password) === null;
}

export function isRegisterPasswordValid(password: string): boolean {
  return validateRegisterPassword(password) === null;
}

/** 中国大陆手机号 */
export const PHONE_RE = /^1[3-9]\d{9}$/;

export function sanitizePhoneInput(value: string): string {
  return value.replace(/\D/g, '').slice(0, 11);
}

export function validatePhone(phone: string): string | null {
  if (!phone) return '请输入手机号';
  if (!PHONE_RE.test(phone)) return '请输入正确的手机号';
  return null;
}

export function isPhoneValid(phone: string): boolean {
  return validatePhone(phone) === null;
}

/** 短信验证码：6 位数字 */
export function sanitizeSmsCodeInput(value: string): string {
  return value.replace(/\D/g, '').slice(0, 6);
}

export function validateSmsCode(code: string): string | null {
  if (!code) return '请输入验证码';
  if (!/^\d{6}$/.test(code)) return '请输入 6 位验证码';
  return null;
}

export function isSmsCodeValid(code: string): boolean {
  return validateSmsCode(code) === null;
}
