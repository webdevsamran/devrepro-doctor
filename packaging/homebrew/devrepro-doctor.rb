# Homebrew formula. Template: see packaging/README.md.
#
# A tap rather than homebrew-core. Core has a notability threshold this project
# does not meet, and submitting anyway wastes a maintainer's time.
class DevreproDoctor < Formula
  include Language::Python::Virtualenv

  desc "Diagnose why this machine cannot build this repository"
  homepage "https://github.com/webdevsamran/devrepro-doctor"
  url "PLACEHOLDER_SDIST_URL"
  sha256 "PLACEHOLDER_SDIST_SHA256"
  license "Apache-2.0"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    # `--version` rather than a scan: a formula test runs in a sandbox where a
    # full diagnostic would report on the sandbox, slowly, and prove nothing.
    assert_match "devrepro", shell_output("#{bin}/devrepro --version")
  end
end
