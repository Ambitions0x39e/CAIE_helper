#!/usr/bin/env bash
# 发版脚本：改版本号、建 release notes 存根，按需触发构建。
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
  cat <<'USAGE'
用法: scripts/release.sh <版本> [选项]

  -theme "标题"   release notes 的主题
  -ghbuild        推 CI 构建（不建 release）
  -release        提交 + 打 tag + 推，CI 构建完建 draft release
  -lcbuild        本地构建（只出 macOS 的 .dmg）
  -help           显示本说明

例: scripts/release.sh 2.1.0 -theme "错题本导出" -release
USAGE
}

version=""; theme=""; mode=""
while [ $# -gt 0 ]; do
  case "$1" in
    -help|--help|-h) usage; exit 0 ;;
    -theme|--theme) theme="${2:-}"; shift 2 ;;
    -ghbuild|--ghbuild|-release|--release|-lcbuild|--lcbuild)
      mode="${1#-}"; mode="${mode#-}"; shift ;;
    -*) echo "未知参数: $1" >&2; usage >&2; exit 1 ;;
    *) version="$1"; shift ;;
  esac
done

[ -n "$version" ] || { usage >&2; exit 1; }
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "版本号要形如 2.1.0，收到: $version" >&2; exit 1; }

perl -pi -e "s/^version = \".*\"/version = \"$version\"/ if \$. < 10" pyproject.toml
perl -pi -e "s/^(  #define MyAppVersion \").*(\")/\${1}$version\${2}/" packaging/windows/cie-helper.iss

notes="dev/CIE-Helper-Notes/release-notes/v$version.md"
if [ -e "$notes" ]; then
  echo "已存在，未覆盖: $notes"
else
  cat > "$notes" <<NOTES
---
version: $version
date: $(date +%F)
theme: ${theme:-TODO}
status: draft
commit: TODO
installer_win: dist/cie-helper-$version-setup.exe
installer_mac: dist/cie-helper-$version-setup.dmg
tags:
  - release
---

# v$version — $(date +%F)

**主题：${theme:-TODO}**

### 新增

- TODO

### 修复

- TODO

### 其他

- TODO
NOTES
  echo "已建: $notes"
fi
echo "版本号已改为 $version（pyproject.toml + cie-helper.iss）"

site=Query_System/static/cie-helper.html
ssh aliyun "perl -pi -e 's/v[0-9]+\.[0-9]+\.[0-9]+/v$version/g; s/cie-helper-[0-9]+\.[0-9]+\.[0-9]+-setup/cie-helper-$version-setup/g' \$HOME/$site && grep -n '$version' \$HOME/$site" \
  || echo "站点未更新（ssh aliyun 失败）"

case "$mode" in
  ghbuild)
    gh workflow run build.yml --ref "$(git branch --show-current)"
    ;;
  release)
    git commit -m "chore: $version" pyproject.toml packaging/windows/cie-helper.iss "$notes"
    git push
    # tag 必须和 pyproject 的 version 一致，否则 CI 第一步就失败
    git tag "v$version"
    git push origin "v$version"
    ;;
  lcbuild)
    npm run build --prefix frontend
    uv run pyinstaller packaging/cie-helper.spec --noconfirm
    ./packaging/macos/build-dmg.sh
    ;;
esac
