/**
 * GitHub Pages에서 저장소 assets 폴더 목록을 자동으로 가져오려면
 * 아래 github.enabled 를 true 로 두고 owner, repo 를 본인 저장소에 맞게 수정하세요.
 * (공개 저장소만 브라우저에서 인증 없이 조회 가능, API 분당 요청 한도 있음)
 */
window.OBJ_SITE = {
  github: {
    enabled: false,
    owner: 'YOUR_GITHUB_USER',
    repo: 'py',
    branch: 'main',
    assetsPath: 'obj/assets'
  }
};
