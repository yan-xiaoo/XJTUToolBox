# 检查存储库及其镜像中，哪个 API 的速度最快
# 原始代码来自：https://github.com/moesnow/March7thAssistant/blob/main/tasks/base/fastest_mirror.py


import time
import requests
import concurrent.futures


class FastestMirror:
    # @staticmethod
    # def get_github_mirror(download_url):
    #     # mirror_urls = [
    #     #     download_url,
    #     #     f"https://github.kotori.top/{download_url}",
    #     # ]
    #     # return FastestMirror.find_fastest_mirror(mirror_urls, 5)
    #     return f"https://github.kotori.top/{download_url}"

    @staticmethod
    def get_github_api_mirror(user, repo, latest=True):
        # mirror_urls = [
        #     f"https://api.github.com/repos/{user}/{repo}/releases/latest",
        #     f"https://github.kotori.top/https://api.github.com/repos/{user}/{repo}/releases/latest",
        # ]
        # return FastestMirror.find_fastest_mirror(mirror_urls, 5)

        if latest:
            return f"https://api.github.com/repos/{user}/{repo}/releases/latest"
        else:
            return f"https://api.github.com/repos/{user}/{repo}/releases"

    @staticmethod
    def find_fastest_mirror(mirror_urls, timeout=5):
        """测速并找到最快的镜像。"""
        def check_mirror(mirror_url):
            try:
                start_time = time.time()
                response = requests.head(mirror_url, timeout=timeout, allow_redirects=True)
                end_time = time.time()
                if response.status_code == 200:
                    return mirror_url, end_time - start_time
            except Exception:
                pass
            return None, None

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(check_mirror, url) for url in mirror_urls]
            fastest_mirror, _ = min((future.result() for future in concurrent.futures.as_completed(futures)), key=lambda x: (x[1] is not None, x[1]), default=(None, None))

        return fastest_mirror if fastest_mirror else mirror_urls[0]