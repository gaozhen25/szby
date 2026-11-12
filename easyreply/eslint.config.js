// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ['dist/*', 'dist-*/*'],
  },
  {
    // Metro 不做 tree-shaking：从 barrel 里按名字导入，整个包都会进首屏 bundle。
    // `@ant-design/icons` 尤其夸张（847 个图标、6.6MB path 数据），
    // 所以图标统一走 src/ui/web/antd-icons.ts 的叶子导入。
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: '@ant-design/icons',
              message:
                '请从 @/ui/web/antd-icons 导入（叶子路径按需引入）。新图标先加到 src/ui/web/antd-icons.ts。',
            },
          ],
        },
      ],
    },
  },
  {
    // 图标聚合模块本身必须直接引叶子路径
    files: ['src/ui/web/antd-icons.ts'],
    rules: { 'no-restricted-imports': 'off' },
  },
]);
