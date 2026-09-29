import type { InputHTMLAttributes } from "react";

/**
 * A masked field for a secret that is not a sign-in (new passwords, API keys).
 *
 * Password managers (KeePassXC, Bitwarden, 1Password, LastPass...) find sign-in forms by
 * their `type="password"` fields and ignore `autocomplete="off"`: they would offer to
 * fill or save these ones. So this is a text field whose characters are hidden by CSS
 * (`.secret-input`), with the attributes the managers that support one skip. Only the
 * login page has a real password field.
 */
export function SecretInput({ className, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  return (
    <input
      {...props}
      className={`${className ?? "field__input"} secret-input`}
      type="text"
      autoComplete="off"
      autoCapitalize="off"
      autoCorrect="off"
      spellCheck={false}
      data-1p-ignore=""
      data-lpignore="true"
      data-bwignore=""
      data-form-type="other"
    />
  );
}
