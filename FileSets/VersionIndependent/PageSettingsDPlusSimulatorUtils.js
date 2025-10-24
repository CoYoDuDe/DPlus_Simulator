.pragma library

function normalizePrefix(prefix) {
        if (!prefix)
                return "";
        var value = prefix.toString();
        return value.replace(/\/+$/, "");
}

function normalizeSuffix(suffix) {
        if (!suffix)
                return "";
        var value = suffix.toString();
        return value.replace(/^\/+/, "");
}

function path(prefix, suffix) {
        var normalizedPrefix = normalizePrefix(prefix);
        var normalizedSuffix = normalizeSuffix(suffix);

        if (!normalizedPrefix.length)
                return normalizedSuffix;
        if (!normalizedSuffix.length)
                return normalizedPrefix;
        return normalizedPrefix + "/" + normalizedSuffix;
}
