/** 非密钥：Web 打包读不到 gitignore 的 .env 时使用。本地 .env / extra.apiHost 优先。 */
export const PUBLIC_API_HOSTS: Record<string, string> = {
  test: 'http://8.211.151.224',
  development: 'http://8.211.151.224',
  production: 'https://service.humanlike.life',
};
