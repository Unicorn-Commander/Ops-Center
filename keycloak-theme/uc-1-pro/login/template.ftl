<#-- uc-1-pro login layout for every page WITHOUT its own uc-1-pro template.
     Based on Keycloak 26.6.3 theme/base/login/template.ftl (same macro signature and
     nested sections); only the page chrome is uc-1-pro. Added 2026-10-24 (PO a93c6f50). -->
<#import "footer.ftl" as loginFooter>
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<!DOCTYPE html>
<html class="${properties.kcHtmlClass!}" lang="${lang}"<#if realm.internationalizationEnabled> dir="${(locale.rtl)?then('rtl','ltr')}"</#if>>

<head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <meta name="robots" content="noindex, nofollow">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <#if properties.meta?has_content>
        <#list properties.meta?split(' ') as meta>
            <meta name="${meta?split('==')[0]}" content="${meta?split('==')[1]}"/>
        </#list>
    </#if>
    <title>${title!}</title>
    <link rel="icon" href="${url.resourcesPath}/img/favicon.ico" />
    <#if properties.stylesCommon?has_content>
        <#list properties.stylesCommon?split(' ') as style>
            <link href="${url.resourcesCommonPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <#if properties.styles?has_content>
        <#list properties.styles?split(' ') as style>
            <link href="${url.resourcesPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <style>
        /* uc-1-pro: shared layout for every login page that has no uc-1-pro override
           (first-broker review, OTP, consent, update-email, username-first, ...). */
        .uc1-generic #kc-content-wrapper > form, .uc1-generic #kc-form-wrapper form { margin-top: 8px; }
        .uc1-generic #kc-page-title { font-size: 22px; font-weight: 700; color: var(--uc1-text-primary, #fff); text-align: center; margin: 4px 0 18px; }
        .uc1-generic #kc-content div { margin-bottom: 14px; }
        .uc1-generic #kc-content div:empty { margin: 0; }
        .uc1-generic .uc1-submit-btn { display: block; width: 100%; padding: 12px 16px; margin-top: 6px; border-radius: 10px; color: #fff; font-weight: 600; letter-spacing: 1px; cursor: pointer;
            background: linear-gradient(135deg, var(--uc1-purple-primary, #8b5cf6), var(--uc1-purple-dark, #6d28d9)); }
        .uc1-generic .uc1-secondary-btn { background: rgba(255,255,255,0.08) !important; border: 1px solid rgba(255,255,255,0.25) !important; }
        .uc1-generic #kc-content, .uc1-generic #kc-content p, .uc1-generic #kc-content span, .uc1-generic #kc-content li { color: var(--uc1-text-primary, #fff); }
        .uc1-generic #kc-content a { color: var(--uc1-purple-light, #c4b5fd); }
        .uc1-generic #kc-attempted-username { color: var(--uc1-text-primary, #fff); font-weight: 600; margin-right: 8px; }
        .uc1-generic .uc1-alert { border-radius: 10px; padding: 10px 14px; background: rgba(255,255,255,0.1); }
        .uc1-generic .kc-tooltip-text { display: none; }
        .uc1-generic .uc1-social-links li { margin-bottom: 10px; }
        .uc1-generic #kc-social-providers hr, .uc1-generic #kc-social-providers + hr { border: 0; border-top: 1px solid rgba(255,255,255,0.15); margin: 18px 0 8px; }
        .uc1-generic #kc-social-providers h2, .uc1-generic #kc-social-providers h4 { color: var(--uc1-text-secondary, #ddd6fe); font-size: 14px; font-weight: 600; text-align: center; text-transform: uppercase; letter-spacing: 1px; margin: 12px 0; }
        .uc1-generic #kc-content .uc1-error-text { color: var(--uc1-error, #fca5a5); font-size: 13px; }
        .uc1-generic select { width: 100%; padding: 10px 14px; border-radius: 10px; background: rgba(255,255,255,0.1); color: var(--uc1-text-primary, #fff); border: 1px solid rgba(255,255,255,0.25); }
    </style>
    <#if properties.scripts?has_content>
        <#list properties.scripts?split(' ') as script>
            <script src="${url.resourcesPath}/${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <script type="importmap">
        {
            "imports": {
                "rfc4648": "${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js"
            }
        }
    </script>
    <script src="${url.resourcesPath}/js/menu-button-links.js" type="module"></script>
    <#if scripts??>
        <#list scripts as script>
            <script src="${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <script type="module">
        <#outputformat "JavaScript">
        import { startSessionPolling } from ${(url.resourcesPath + "/js/authChecker.js")?c};

        startSessionPolling(
            ${url.ssoLoginInOtherTabsUrl?c}
        );
        </#outputformat>
    </script>
    <script type="module">
        document.addEventListener("click", (event) => {
            const link = event.target.closest("a[data-once-link]");

            if (!link) {
                return;
            }

            if (link.getAttribute("aria-disabled") === "true") {
                event.preventDefault();
                return;
            }

            const { disabledClass } = link.dataset;

            if (disabledClass) {
                link.classList.add(...disabledClass.trim().split(/\s+/));
            }

            link.setAttribute("role", "link");
            link.setAttribute("aria-disabled", "true");
        });
    </script>
    <#if authenticationSession??>
        <script type="module">
            <#outputformat "JavaScript">
            import { checkAuthSession } from ${(url.resourcesPath + "/js/authChecker.js")?c};

            checkAuthSession(
                ${authenticationSession.authSessionIdHash?c}
            );
            </#outputformat>
        </script>
    </#if>
</head>

<body class="uc1-pro-login uc1-generic" data-page-id="login-${pageId}">
<div class="login-pf-page">
  <div class="uc1-background"></div>
  <div class="container">
   <div class="row">
    <div class="col-sm-8 col-sm-offset-2 col-md-6 col-md-offset-3 col-lg-6 col-lg-offset-3">
    <div class="card-pf uc1-card">
        <header class="login-pf-header">
            <div class="uc1-logo-container">
                <img src="${url.resourcesPath}/img/colonel-logo.png" alt="" class="uc1-logo" onerror="this.style.display='none'" />
            </div>
            <#if realm.internationalizationEnabled  && locale.supported?size gt 1>
                <div class="${properties.kcLocaleMainClass!}" id="kc-locale">
                    <div id="kc-locale-wrapper" class="${properties.kcLocaleWrapperClass!}">
                        <div id="kc-locale-dropdown" class="menu-button-links ${properties.kcLocaleDropDownClass!}">
                            <button tabindex="1" id="kc-current-locale-link" aria-label="${msg("languages")}" aria-haspopup="true" aria-expanded="false" aria-controls="language-switch1">${locale.current}</button>
                            <ul role="menu" tabindex="-1" aria-labelledby="kc-current-locale-link" aria-activedescendant="" id="language-switch1" class="${properties.kcLocaleListClass!}">
                                <#assign i = 1>
                                <#list locale.supported as l>
                                    <li class="${properties.kcLocaleListItemClass!}" role="none">
                                        <a role="menuitem" id="language-${i}" class="${properties.kcLocaleItemClass!}" href="${l.url}">${l.label}</a>
                                    </li>
                                    <#assign i++>
                                </#list>
                            </ul>
                        </div>
                    </div>
                </div>
            </#if>
        <#if !(auth?has_content && auth.showUsername() && !auth.showResetCredentials())>
            <#if displayRequiredFields>
                <div class="${properties.kcContentWrapperClass!}">
                    <div class="${properties.kcLabelWrapperClass!} subtitle">
                        <span class="subtitle"><span class="required">*</span> ${msg("requiredFields")}</span>
                    </div>
                    <div class="col-md-10">
                        <h1 id="kc-page-title"><#nested "header"></h1>
                    </div>
                </div>
            <#else>
                <h1 id="kc-page-title"><#nested "header"></h1>
            </#if>
        <#else>
            <#if displayRequiredFields>
                <div class="${properties.kcContentWrapperClass!}">
                    <div class="${properties.kcLabelWrapperClass!} subtitle">
                        <span class="subtitle"><span class="required">*</span> ${msg("requiredFields")}</span>
                    </div>
                    <div class="col-md-10">
                        <#nested "show-username">
                        <div id="kc-username" class="${properties.kcFormGroupClass!}">
                            <label id="kc-attempted-username">${auth.attemptedUsername}</label>
                            <a id="reset-login" href="${url.loginRestartFlowUrl}" aria-label="${msg("restartLoginTooltip")}">
                                <div class="kc-login-tooltip">
                                    <i class="${properties.kcResetFlowIcon!}"></i>
                                    <span class="kc-tooltip-text">${msg("restartLoginTooltip")}</span>
                                </div>
                            </a>
                        </div>
                    </div>
                </div>
            <#else>
                <#nested "show-username">
                <div id="kc-username" class="${properties.kcFormGroupClass!}">
                    <label id="kc-attempted-username">${auth.attemptedUsername}</label>
                    <a id="reset-login" href="${url.loginRestartFlowUrl}" aria-label="${msg("restartLoginTooltip")}">
                        <div class="kc-login-tooltip">
                            <i class="${properties.kcResetFlowIcon!}"></i>
                            <span class="kc-tooltip-text">${msg("restartLoginTooltip")}</span>
                        </div>
                    </a>
                </div>
            </#if>
        </#if>
      </header>
      <div id="kc-content">
        <div id="kc-content-wrapper">

          <#-- App-initiated actions should not see warning messages about the need to complete the action -->
          <#-- during login.                                                                               -->
          <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
              <div class="alert-${message.type} ${properties.kcAlertClass!} pf-m-<#if message.type = 'error'>danger<#else>${message.type}</#if>">
                  <div class="pf-c-alert__icon">
                      <#if message.type = 'success'><span class="${properties.kcFeedbackSuccessIcon!}"></span></#if>
                      <#if message.type = 'warning'><span class="${properties.kcFeedbackWarningIcon!}"></span></#if>
                      <#if message.type = 'error'><span class="${properties.kcFeedbackErrorIcon!}"></span></#if>
                      <#if message.type = 'info'><span class="${properties.kcFeedbackInfoIcon!}"></span></#if>
                  </div>
                      <span class="${properties.kcAlertTitleClass!}">${kcSanitize(message.summary)?no_esc}</span>
              </div>
          </#if>

          <#nested "form">

          <#if auth?has_content && auth.showTryAnotherWayLink()>
              <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post">
                  <div class="${properties.kcFormGroupClass!}">
                      <input type="hidden" name="tryAnotherWay" value="on"/>
                      <a href="#" id="try-another-way"
                         onclick="document.forms['kc-select-try-another-way-form'].requestSubmit();return false;">${msg("doTryAnotherWay")}</a>
                  </div>
              </form>
          </#if>

          <#nested "socialProviders">

          <#if displayInfo>
              <div id="kc-info" class="${properties.kcSignUpClass!}">
                  <div id="kc-info-wrapper" class="${properties.kcInfoAreaWrapperClass!}">
                      <#nested "info">
                  </div>
              </div>
          </#if>
        </div>
      </div>

      <@loginFooter.content/>
      <footer class="uc1-footer">
          <p>&copy; 2026 Magic Unicorn Unconventional Technology &amp; Stuff Inc</p>
      </footer>
    </div>
    </div>
   </div>
  </div>
</div>
<script>
  // Give Keycloak's stock markup the uc-1-pro classes so css/login.css styles it.
  (function () {
    var root = document.querySelector('.uc1-generic #kc-content');
    if (!root) return;
    function add(sel, cls) { root.querySelectorAll(sel).forEach(function (el) { cls.split(' ').forEach(function (c) { el.classList.add(c); }); }); }
    add('input[type=text], input[type=email], input[type=password], input[type=tel], input[type=number], input:not([type]), textarea', 'form-control uc1-input');
    add('label', 'uc1-label');
    add('input[type=checkbox], input[type=radio]', 'uc1-check');
    root.querySelectorAll('label').forEach(function (l) { if (l.querySelector('input[type=checkbox], input[type=radio]')) { l.classList.remove('uc1-label'); l.classList.add('uc1-checkbox-label'); } });
    add('input[type=submit], button[type=submit], button:not([type])', 'uc1-submit-btn');
    add('input[name=cancel], button[name=cancel], #kc-cancel', 'uc1-secondary-btn');
    add('#kc-social-providers ul, .kc-social-links', 'uc1-social-links');
    add('#kc-social-providers a', 'uc1-social-link');
    add('[class*="alert-"]', 'uc1-alert');
    add('[id^="input-error"], .kc-feedback-text', 'uc1-error-text');
  })();
</script>
</body>
</html>
</#macro>
