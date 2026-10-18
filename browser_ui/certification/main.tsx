/** Isolated certification-only entrypoint. Not part of the regular browser bundle.
 * Never serve this through the production read-only launcher.
 */
import React from "react";
import {createRoot} from "react-dom/client";
import {GuardedRunControls} from "../src/GuardedRunControls";
import "../src/style.css";

function CertificationOnly() {
  const [token, setToken] = React.useState("");
  const [armed, setArmed] = React.useState(false);
  return <main>
    <h1>CSL guarded browser certification — isolated test only</h1>
    <p role="note">This page is not a release switch. Use only with a separately
      provisioned localhost, opt-in FastAPI certification server and isolated
      configuration/output roots. Production server routes remain disabled.</p>
    <label htmlFor="cert-token">Test-only local bearer token</label>
    <input id="cert-token" type="password" autoComplete="off" value={token}
      onChange={event => {setArmed(false); setToken(event.target.value);}} />
    <label htmlFor="cert-arm"><input id="cert-arm" type="checkbox" checked={armed}
      onChange={event => setArmed(event.target.checked)} />
      Arm experimental certification controls (requires separate server authorization)
    </label>
    <GuardedRunControls enabled={armed && token.length > 0} token={token}/>
  </main>;
}
const target = document.getElementById("root");
if (!target) throw new Error("Missing certification root");
createRoot(target).render(<CertificationOnly/>);
