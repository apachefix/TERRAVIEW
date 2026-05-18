# Change Log

## [1.0.3] 2021-12-04
### Improvements & Fixes

- Bump Django Codebase to [v2.0.4](https://github.com/app-generator/boilerplate-code-django-dashboard/releases)
- Patch #1: SCSS Compilation Error: argument `$color` of `rgba($color, $alpha)` must be a color 

## [1.0.2] 2021-09-09
### Improvements & Fixes

- Bump Django Codebase to [v2.0.2](https://github.com/app-generator/boilerplate-code-django-dashboard/releases)
  - Dependencies update (all packages)
    - Use Django==3.2.6 (latest stable version)
  - Better Code formatting
  - Improved Files organization
  - Optimize imports
  - Docker Scripts Update 
- Tooling
  - SCSS compilation via Gulp
  - Update README with build instructions: `Recompile CSS` section     
- Fixes: 
  - Patch 500 Error when authenticated users access `admin` path (no slash at the end)
  - Patch: Update sidebar to reflect the current page 
  - Patch [#16](https://github.com/app-generator/boilerplate-code-django-dashboard/issues/16): Minor issue in Docker 

## [1.0.1] 2020-03-23
### Fixes 

- Bump Codebase: [Django Dashboard](https://github.com/app-generator/boilerplate-code-django-dashboard) v1.0.4
- Bump UI: [Jinja Gradient PRO](https://github.com/app-generator/jinja-gradient-pro) v1.0.1

## [1.0.0] 2020-06-16
### Initial Release

- Code-base version - v1.0.1
