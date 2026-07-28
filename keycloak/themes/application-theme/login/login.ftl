<#import "template.ftl" as layout>
<@layout.registrationLayout; section>
    <#if section = "form">
        <div class="login-container">
                <div class="login-card">
                <#-- back button disabled
                <div class="login-back-row">
                    <a href="__HOME_PAGE_URL__" class="login-back-btn">
                        <span class="material-icons">arrow_back</span>
                        Back
                    </a>
                </div>
                -->
                <div class="login-header">
                    <img src="${url.resourcesPath}/img/laif_logo.png" alt="Logo" class="login-logo" />
                    <h1 class="login-title">Sign in to AISC</h1>
                </div>

                <div class="login-body">
                    <form id="kc-form-login" action="${url.loginAction}" method="post">
                        <div class="form-group">
                            <label for="username" class="form-label">${msg("usernameOrEmail")}</label>
                            <input id="username" class="form-input" name="username" value="${(login.username!'')}" type="text" autofocus autocomplete="username" />
                        </div>

                        <div class="form-group">
                            <label for="password" class="form-label">${msg("password")}</label>
                            <input id="password" class="form-input" name="password" type="password" autocomplete="current-password" />
                        </div>

                        <#if realm.rememberMe && !usernameEditDisabled??>
                            <div class="form-group-checkbox">
                                <label class="checkbox-label">
                                    <input id="rememberMe" name="rememberMe" type="checkbox" <#if login.rememberMe??>checked</#if> />
                                    <span>${msg("rememberMe")}</span>
                                </label>
                            </div>
                        </#if>

                        <#if message?has_content && message.type = 'error' || messagesPerField.existsError('password') || messagesPerField.existsError('username')>
                            <div class="alert-error">
                                <span class="material-icons alert-icon">error_outline</span>
                                <span>${message.summary!messagesPerField.getFirstError('password')!messagesPerField.getFirstError('username')!'Invalid username or password'}</span>
                            </div>
                        </#if>

                        <button type="submit" class="btn-primary">${msg("doLogIn")}</button>
                    </form>
                </div>

            </div>
        </div>
    </#if>
</@layout.registrationLayout>
