/**
 * Expo Config Plugin：为 Android Gradle 注入国内 Maven 镜像，避免 dl.google.com TLS/网络问题
 */
const { withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const MARKER = 'maven.aliyun.com/repository/google';

const MIRROR_LINES = [
  "maven { url 'https://maven.aliyun.com/repository/google' }",
  "maven { url 'https://maven.aliyun.com/repository/public' }",
  "maven { url 'https://maven.aliyun.com/repository/gradle-plugin' }",
];

function injectMirrorsIntoRepositoriesBlock(block) {
  if (block.includes(MARKER)) return block;
  const indent = '    ';
  const mirrorBlock = MIRROR_LINES.map((line) => `${indent}${line}`).join('\n');
  return block.replace(/(\n[ \t]*)(google\(\))/g, `$1${mirrorBlock}\n$1$2`);
}

function patchBuildGradle(content) {
  if (content.includes(MARKER)) return content;

  let next = content;
  next = next.replace(
    /buildscript\s*\{\s*repositories\s*\{([\s\S]*?)\n\s*\}/,
    (full, inner) => `buildscript {\n  repositories {${injectMirrorsIntoRepositoriesBlock(inner)}\n  }`,
  );
  next = next.replace(
    /allprojects\s*\{\s*repositories\s*\{([\s\S]*?)\n\s*\}/,
    (full, inner) => `allprojects {\n  repositories {${injectMirrorsIntoRepositoriesBlock(inner)}\n  }`,
  );
  return next;
}

function withAndroidMavenMirrors(config) {
  return withDangerousMod(config, [
    'android',
    async (cfg) => {
      const gradlePath = path.join(cfg.modRequest.platformProjectRoot, 'build.gradle');
      if (!fs.existsSync(gradlePath)) return cfg;
      const original = fs.readFileSync(gradlePath, 'utf8');
      const patched = patchBuildGradle(original);
      if (patched !== original) {
        fs.writeFileSync(gradlePath, patched);
      }
      return cfg;
    },
  ]);
}

module.exports = withAndroidMavenMirrors;
