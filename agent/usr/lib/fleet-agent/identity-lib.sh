#!/bin/bash
# /usr/lib/fleet-agent/identity-lib.sh
# ─────────────────────────────────────────────────────────────────────────────
# Strict, INERT parser and writer for /etc/fleet/device-identity.conf.
#
# The identity file is DATA, never code. It is NEVER passed to `source` or `.`:
# every consumer of the file (firstboot.sh, generate-config.sh, heartbeat.sh)
# calls fleet_identity_parse below, which reads the file line by line and
# rejects anything that is not a contract key holding a value made exclusively
# of the allowed character set.
#
# Contract source of truth:
#   FleetBits-api/app/contracts/device_identity.py
# The lists below are a DUPLICATE of that module, kept honest by the cross-repo
# key-set comparison test (FleetBits-api/tests/test_device_identity_contract.py
# and tests/identity_contract.bats here).
#
# After a successful parse each key K is available as ${FLEET_ID_K}. The prefix
# is deliberate: it keeps identity values out of the plain environment so they
# cannot silently shadow or be shadowed by a process environment variable.
# ─────────────────────────────────────────────────────────────────────────────

# Bump together with CONTRACT_VERSION in the Python module.
FLEET_IDENTITY_CONTRACT_VERSION=1

# Every key of the contract, in canonical file order.
FLEET_IDENTITY_KEYS=(
  DEVICE_ID
  SITE_ID
  ZONE_ID
  DEVICE_ROLE
  PROFILE
  ENVIRONMENT
  RING
  FLEET_API_URL
  FLEET_METRICS_URL
  FLEET_LOGS_URL
  FLEET_AGENT_TOKEN
  REPO_BASIC_TOKEN
  HEADSCALE_PREAUTH_KEY
  MQTT_BROKER_HOST
  MQTT_BROKER_PORT
  MQTT_USERNAME
  MQTT_PASSWORD
  ENABLE_MQTT_EXPORTER
  ENABLE_PROCESS_EXPORTER
  SCRAPE_INTERVAL
)

# Keys that must always be present but may legitimately carry an empty value.
FLEET_IDENTITY_OPTIONAL_KEYS=(
  PROFILE
  REPO_BASIC_TOKEN
  HEADSCALE_PREAUTH_KEY
  MQTT_USERNAME
  MQTT_PASSWORD
)

# Keys carrying a credential: never log them, redact them from diagnostics.
FLEET_IDENTITY_SECRET_KEYS=(
  FLEET_AGENT_TOKEN
  REPO_BASIC_TOKEN
  HEADSCALE_PREAUTH_KEY
  MQTT_PASSWORD
)

# Allowed value characters. Excludes whitespace, quotes, backslash, '$', '`',
# ';', '&' and '|'. The shell metacharacters keep the format inert; excluding
# '|', '&' and '\' additionally keeps every value safe to use as sed
# replacement text in generate-config.sh, which uses '|' as its delimiter.
FLEET_IDENTITY_VALUE_PATTERN='^[A-Za-z0-9._:/@=+,~-]*$'

# fleet_identity_version — the contract version this library implements.
fleet_identity_version() {
  printf '%s\n' "${FLEET_IDENTITY_CONTRACT_VERSION}"
}

fleet_identity_err() {
  echo "ERROR: device-identity: $*" >&2
}

_fleet_identity_contains() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [ "${item}" = "${needle}" ]; then
      return 0
    fi
  done
  return 1
}

fleet_identity_is_secret() {
  _fleet_identity_contains "$1" "${FLEET_IDENTITY_SECRET_KEYS[@]}"
}

# fleet_identity_set KEY VALUE — validate one pair and store it as FLEET_ID_KEY.
fleet_identity_set() {
  # The charset check below is a bracket expression holding ranges (A-Z, a-z,
  # 0-9). What a range covers is decided by the COLLATION ORDER of the active
  # locale, so the same pattern does not decide the same thing everywhere: under
  # a glibc UTF-8 locale 'A-Z' and 'a-z' sweep in accented letters, and 'rôle'
  # or 'aé' were ACCEPTED here while the Python contract
  # (FleetBits-api/app/contracts/device_identity.py, re.match on the identical
  # spelling) rejected them. None of the consumers pins a locale — the systemd
  # units and container-entrypoint.sh inherit whatever the host has — so the
  # verdict was a property of the machine, not of the contract.
  #
  # `local LC_ALL=C` pins the collation for the duration of this function only
  # (bash re-reads its locale on assignment, and `local` restores the caller's
  # value on return). It does not widen the accepted set: C collation is the
  # narrowest reading of these ranges, exactly the ASCII one the Python side
  # applies. Cross-checked under several locales by
  # test_python_and_bash_validators_agree_on_every_probe.
  local LC_ALL=C
  local key="$1"
  local value="$2"

  if ! _fleet_identity_contains "${key}" "${FLEET_IDENTITY_KEYS[@]}"; then
    fleet_identity_err "key '${key}' is not part of the device identity contract"
    return 1
  fi
  if ! [[ "${value}" =~ $FLEET_IDENTITY_VALUE_PATTERN ]]; then
    # The value itself is never printed: it may be a credential.
    fleet_identity_err "value of '${key}' contains a character outside ${FLEET_IDENTITY_VALUE_PATTERN}"
    return 1
  fi
  if [ -z "${value}" ] && ! _fleet_identity_contains "${key}" "${FLEET_IDENTITY_OPTIONAL_KEYS[@]}"; then
    fleet_identity_err "'${key}' must not be empty"
    return 1
  fi

  # Indirect assignment, not evaluation: ${key} was whitelisted above and the
  # value is never interpreted by the shell.
  printf -v "FLEET_ID_${key}" '%s' "${value}"
  return 0
}

# fleet_identity_parse FILE — read FILE and populate FLEET_ID_* .
# Returns non-zero, with a message on stderr, on any deviation:
#   unknown key, duplicate key, malformed line, forbidden character,
#   empty value for a mandatory key, missing key.
fleet_identity_parse() {
  local file="$1"
  local lineno=0
  local line key value nul_scan
  local -a seen=()

  if [ ! -f "${file}" ]; then
    fleet_identity_err "${file} not found"
    return 1
  fi

  # A NUL byte has to be caught BEFORE the line loop, because `IFS= read -r`
  # silently DROPS NUL bytes instead of reporting them: a line
  # `DEVICE_ROLE=a<NUL>b` reached fleet_identity_set as the value `ab`, passed
  # the charset check and was stored — a silent mutation of the file's content,
  # accepted with status 0, while the Python contract
  # (app/contracts/device_identity.py:parse) rejects the same bytes. The two
  # sides must return the same verdict on the same bytes; the file is data, and
  # data that cannot be read faithfully is refused, not repaired.
  #
  # `read -d ''` reads up to the first NUL: it returns 0 only when it actually
  # found that delimiter, and non-zero when it reached EOF without one. So a
  # successful read here means "this file contains a NUL".
  if IFS= read -r -d '' nul_scan < "${file}"; then
    # nul_scan holds everything that precedes the first NUL, so the number of
    # newlines in it locates the offending line for the operator.
    local before_nul="${nul_scan//[!$'\n']/}"
    fleet_identity_err "${file}:$((${#before_nul} + 1)): contains a NUL byte"
    return 1
  fi

  # Clear any previous state so a stale value can never survive a failed parse.
  for key in "${FLEET_IDENTITY_KEYS[@]}"; do
    unset "FLEET_ID_${key}"
  done

  while IFS= read -r line || [ -n "${line}" ]; do
    lineno=$((lineno + 1))
    line="${line%$'\r'}"
    case "${line}" in
      '' | '#'*) continue ;;
    esac

    if [[ "${line}" != *=* ]]; then
      fleet_identity_err "${file}:${lineno}: malformed line, expected KEY=value"
      return 1
    fi
    key="${line%%=*}"
    value="${line#*=}"

    if _fleet_identity_contains "${key}" "${seen[@]}"; then
      fleet_identity_err "${file}:${lineno}: duplicate key '${key}'"
      return 1
    fi
    if ! fleet_identity_set "${key}" "${value}"; then
      fleet_identity_err "${file}:${lineno}: rejected"
      return 1
    fi
    seen+=("${key}")
  done < "${file}"

  for key in "${FLEET_IDENTITY_KEYS[@]}"; do
    if ! _fleet_identity_contains "${key}" "${seen[@]}"; then
      fleet_identity_err "${file}: required key '${key}' is missing"
      return 1
    fi
  done

  return 0
}

# fleet_identity_require KEY... — assert the given keys hold a non-empty value.
fleet_identity_require() {
  local key varname rc=0
  for key in "$@"; do
    varname="FLEET_ID_${key}"
    if [ -z "${!varname:-}" ]; then
      fleet_identity_err "required variable ${key} is not set"
      rc=1
    fi
  done
  return "${rc}"
}

# fleet_identity_get KEY — print the parsed value (empty string if unset).
fleet_identity_get() {
  local varname="FLEET_ID_$1"
  printf '%s' "${!varname:-}"
}

# fleet_identity_render — write the full contract, in canonical order, from the
# currently loaded FLEET_ID_* values. Used by the container producer.
fleet_identity_render() {
  local key varname
  for key in "${FLEET_IDENTITY_KEYS[@]}"; do
    varname="FLEET_ID_${key}"
    if [ -z "${!varname+set}" ]; then
      fleet_identity_err "cannot render: '${key}' has not been set"
      return 1
    fi
    printf '%s=%s\n' "${key}" "${!varname}"
  done
  return 0
}

# fleet_render_template TEMPLATE OUTPUT NAME_PLACEHOLDER=value ...
# ─────────────────────────────────────────────────────────────────────────────
# Render a telemetry template in a SINGLE pass.
#
# Why not `sed -e ... -e ...`: sed applies its -e expressions in sequence to the
# same line, so text that one expression has already substituted is still
# visible to the next one. Every contract value is a plain word made of the
# allowed character set, and a placeholder name is itself a plain word made of
# that same set — so a value can BE the name of a later placeholder. With a
# cascade, DEVICE_ROLE=FLEET_AGENT_TOKEN_PLACEHOLDER made the role expand to the
# device bearer token, which then shipped to Prometheus and Loki as the value of
# the `device_role` label. No whitelist can prevent that: the collision is in
# the substitution mechanism, not in the data.
#
# This renderer scans each line left to right and appends the replacement text
# to an output buffer that is never re-examined, so a substituted value can
# never be reinterpreted as a placeholder. It also fails closed on a placeholder
# it was given no value for, which keeps a renamed template from silently
# leaking the literal token into a generated config.
#
# The template is DATA here as well: awk concatenates strings, it does not
# interpret the replacement text (unlike sed, for which '&' and '\1' are live).
fleet_render_template() {
  local template="$1"
  local output="$2"
  shift 2

  local entry
  for entry in "$@"; do
    if [ "${entry#*=}" = "${entry}" ]; then
      fleet_identity_err "render mapping '${entry}' is not NAME=value"
      return 1
    fi
    if [[ "${entry}" == *$'\n'* ]]; then
      fleet_identity_err "render mapping '${entry%%=*}' contains a newline"
      return 1
    fi
  done

  local mapping
  mapping="$(printf '%s\n' "$@")"

  FLEET_RENDER_MAP="${mapping}" awk '
    BEGIN {
      rc = 0
      n = split(ENVIRON["FLEET_RENDER_MAP"], lines, "\n")
      for (i = 1; i <= n; i++) {
        if (lines[i] == "") continue
        eq = index(lines[i], "=")
        if (eq < 2) {
          print "ERROR: device-identity: malformed render mapping" > "/dev/stderr"
          rc = 2
          exit
        }
        map[substr(lines[i], 1, eq - 1)] = substr(lines[i], eq + 1)
      }
    }
    {
      out = ""
      rest = $0
      while (match(rest, /[A-Z][A-Z0-9_]*_PLACEHOLDER/)) {
        token = substr(rest, RSTART, RLENGTH)
        out = out substr(rest, 1, RSTART - 1)
        if (token in map) {
          # Appended to out, which the loop never scans again.
          out = out map[token]
        } else {
          printf "ERROR: device-identity: %s:%d: no value for %s\n", \
            FILENAME, FNR, token > "/dev/stderr"
          rc = 1
          out = out token
        }
        rest = substr(rest, RSTART + RLENGTH)
      }
      print out rest
    }
    END { exit rc }
  ' "${template}" > "${output}" || return 1

  return 0
}

# fleet_identity_redact_pattern — extended regular expression matching the
# secret lines of the contract. Consumed by the Ansible diagnostics playbook
# (grep -v -E) so that redaction can never fall behind the contract.
fleet_identity_redact_pattern() {
  local IFS='|'
  printf '^(%s)=' "${FLEET_IDENTITY_SECRET_KEYS[*]}"
}
