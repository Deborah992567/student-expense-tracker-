// Currency configurations by country
const currencyConfig = {
  "United States": { code: "USD", symbol: "$", locale: "en-US" },
  "United Kingdom": { code: "GBP", symbol: "£", locale: "en-GB" },
  "Nigeria": { code: "NGN", symbol: "₦", locale: "en-NG" },
  "Canada": { code: "CAD", symbol: "C$", locale: "en-CA" },
  "Australia": { code: "AUD", symbol: "A$", locale: "en-AU" },
  "Germany": { code: "EUR", symbol: "€", locale: "de-DE" },
  "France": { code: "EUR", symbol: "€", locale: "fr-FR" },
  "India": { code: "INR", symbol: "₹", locale: "en-IN" },
  "Japan": { code: "JPY", symbol: "¥", locale: "ja-JP" },
  "China": { code: "CNY", symbol: "¥", locale: "zh-CN" },
  "South Africa": { code: "ZAR", symbol: "R", locale: "en-ZA" },
  "Kenya": { code: "KES", symbol: "KSh", locale: "en-KE" },
  "Ghana": { code: "GHS", symbol: "GH₵", locale: "en-GH" },
  "Brazil": { code: "BRL", symbol: "R$", locale: "pt-BR" },
  "Mexico": { code: "MXN", symbol: "$", locale: "es-MX" },
  "Singapore": { code: "SGD", symbol: "S$", locale: "en-SG" },
  "UAE": { code: "AED", symbol: "د.إ", locale: "ar-AE" },
  "Saudi Arabia": { code: "SAR", symbol: "﷼", locale: "ar-SA" },
  "Other": { code: "USD", symbol: "$", locale: "en-US" },
};

const defaultCategories = [
  { name: "Food", budget: 0, color: "#0f9f9a" },
  { name: "Transport", budget: 0, color: "#2563eb" },
  { name: "Books", budget: 0, color: "#7c3aed" },
  { name: "Rent", budget: 0, color: "#159947" },
  { name: "Social", budget: 0, color: "#c18400" },
  { name: "Entertainment", budget: 0, color: "#fb923c" },
  { name: "Health", budget: 0, color: "#d0342c" },
  { name: "School fees", budget: 0, color: "#0b7285" },
  { name: "Textbooks", budget: 0, color: "#5b21b6" },
  { name: "Projects", budget: 0, color: "#7c3aed" },
  { name: "Data/Bills", budget: 0, color: "#0f766e" },
];

const merchantCategoryRules = [
  { pattern: /\buber\b/i, category: "Transport" },
  { pattern: /\blyft\b/i, category: "Transport" },
  { pattern: /\btaxi\b/i, category: "Transport" },
  { pattern: /\bmetro\b|\btrain\b|\bbus\b/i, category: "Transport" },
  { pattern: /\bnetflix\b/i, category: "Entertainment" },
  { pattern: /\bprime video\b|\bdisney\b|\bspotify\b|\bspotify\b/i, category: "Entertainment" },
  { pattern: /\bmtn\b|\bglo\b|\bairtel\b|\b9mobile\b|\bmobile\b/i, category: "Data/Bills" },
  { pattern: /\btuition\b|\bdepartmental\b|\bterm fee\b|\bschool fees\b|\bfees\b/i, category: "School fees" },
  { pattern: /\bbookstore\b|\btextbook\b|\bcourse material\b/i, category: "Textbooks" },
  { pattern: /\bproject\b|\bresearch\b|\bgroup work\b|\blab fee\b/i, category: "Projects" },
  { pattern: /\bgrocer|\bmarket\b|\bcaf\b|\bcoffee\b|\bdining\b|\brestaurant\b/i, category: "Food" },
  { pattern: /\bclinic\b|\bpharmacy\b|\bhealth\b|\bmedical\b/i, category: "Health" },
];

const apiBase = getApiBase();
const tokenKey = "studentExpenseToken";
const verificationEmailKey = "studentExpenseVerificationEmail";
const profileEmailKey = "studentExpenseProfileEmail";
const stateKeyPrefix = "studentExpenseState";
let currentProfile = null;

const defaultState = {
  allowance: 0,
  range: "week",
  period: "monthly", // "monthly" or "weekly"
  customStartDate: daysAgo(7),
  customEndDate: new Date().toISOString().slice(0, 10),
  goal: { name: "Emergency fund", target: 600, saved: 0 },
  expenses: [],
  country: "United States",
  analyticsStartDate: daysAgo(30),
  analyticsEndDate: new Date().toISOString().slice(0, 10),
  recurringExpenses: [],
  savingsCurrencies: [
    { currency: "USD", amount: 0 },
  ],
  totalConvertedBalance: null,
};

let categories = structuredClone(defaultCategories);
let currentUserEmail = localStorage.getItem(profileEmailKey) || "";
let state = loadState(currentUserEmail);
if (Array.isArray(state.categories)) {
  categories = state.categories.map(normalizeCategory);
}
let scannedExpense = null;
let apiOnline = false;
let profileSaveTimer = null;
let goalSaveTimer = null;
const budgetSaveTimers = new Map();
let settingsSaveTimer = null;
let authMode = "login";
let authToken = localStorage.getItem(tokenKey);
let pendingVerificationEmail = localStorage.getItem(verificationEmailKey) || "";
let editingExpenseId = null;
let editingRecurringId = null;
const sessionMessageElem = document.querySelector("#sessionMessage");

const authScreen = document.querySelector("#authScreen");
const appShell = document.querySelector("#appShell");
const authForm = document.querySelector("#authForm");
const authTitle = document.querySelector("#authTitle");
const authNameField = document.querySelector("#authNameField");
const authGenderField = document.querySelector("#authGenderField");
const authFirstName = document.querySelector("#authFirstName");
const authLastName = document.querySelector("#authLastName");
const authGender = document.querySelector("#authGender");
const authEmail = document.querySelector("#authEmail");
const authPassword = document.querySelector("#authPassword");
const authCodeField = document.querySelector("#authCodeField");
const authCode = document.querySelector("#authCode");
const authSubmit = document.querySelector("#authSubmit");
const authMessage = document.querySelector("#authMessage");
const authModeToggle = document.querySelector("#authModeToggle");
const authBackButton = document.querySelector("#authBackButton");
const resendCodeButton = document.querySelector("#resendCodeButton");
const logoutButton = document.querySelector("#logoutButton");
const passwordToggle = document.querySelector("#passwordToggle");
const forgotPasswordLink = document.querySelector("#forgotPasswordLink");
const themeToggle = document.querySelector("#themeToggle");
const expenseForm = document.querySelector("#expenseForm");
const goalForm = document.querySelector("#goalForm");
const categorySelect = document.querySelector("#expenseCategory");
const budgetList = document.querySelector("#budgetList");
const countrySelect = document.querySelector("#countrySelect");
const currencyList = document.querySelector("#currencyList");
const addCurrencyButton = document.querySelector("#addCurrency");
const dateInput = document.querySelector("#expenseDate");
const allowanceInput = document.querySelector("#allowanceInput");
const receiptUpload = document.querySelector("#receiptUpload");
const addScannedExpense = document.querySelector("#addScannedExpense");
const recurringList = document.querySelector("#recurringList");
const themeKey = "studentExpenseTheme";
const recurringForm = document.querySelector("#recurringForm");
const recurringName = document.querySelector("#recurringName");
const recurringAmount = document.querySelector("#recurringAmount");
const recurringCategory = document.querySelector("#recurringCategory");
const recurringFrequency = document.querySelector("#recurringFrequency");
const recurringDayOfMonth = document.querySelector("#recurringDayOfMonth");
const recurringDayOfWeek = document.querySelector("#recurringDayOfWeek");

// Filter and pagination elements
const filterSearch = document.querySelector("#filterSearch");
const filterCategory = document.querySelector("#filterCategory");
const filterStartDate = document.querySelector("#filterStartDate");
const filterEndDate = document.querySelector("#filterEndDate");
const filterMinAmount = document.querySelector("#filterMinAmount");
const filterMaxAmount = document.querySelector("#filterMaxAmount");
const applyFiltersBtn = document.querySelector("#applyFilters");
const clearFiltersBtn = document.querySelector("#clearFilters");
const paginationControls = document.querySelector("#paginationControls");
const prevPageBtn = document.querySelector("#prevPage");
const nextPageBtn = document.querySelector("#nextPage");
const pageInfo = document.querySelector("#pageInfo");

// Pagination state
let currentPage = 1;
let itemsPerPage = 20;
let paginationData = null;
let currentFilters = {};

// Wait for DOM to be ready before initializing
document.addEventListener("DOMContentLoaded", init);

function getApiBase() {
  const configuredApiBase = window.STUDENT_EXPENSE_API_BASE || localStorage.getItem("studentExpenseApiBase");
  if (configuredApiBase) {
    return configuredApiBase.replace(/\/+$/, "");
  }

  const staticDevPorts = new Set(["3000", "5173", "5500", "5501"]);
  if (window.location.protocol === "file:" || staticDevPorts.has(window.location.port)) {
    return "http://127.0.0.1:8003";
  }

  return window.location.origin;
}

async function init() {
  authForm.addEventListener("submit", handleAuthSubmit);
  authModeToggle.addEventListener("click", toggleAuthMode);
  authBackButton.addEventListener("click", returnToSignup);
  resendCodeButton.addEventListener("click", resendVerificationCode);
  const logoutButtonElement = document.querySelector("#logoutButton");
  if (logoutButtonElement) {
    logoutButtonElement.addEventListener("click", logout);
  }
  
  authEmail.addEventListener("input", () => {
    const isValid = isValidEmail(authEmail.value.trim());
    authEmail.style.borderColor = authEmail.value && !isValid ? "var(--red)" : "";
  });

  passwordToggle.addEventListener("click", togglePasswordVisibility);
  if (forgotPasswordLink) {
    forgotPasswordLink.addEventListener("click", handleForgotPassword);
  }
  if (themeToggle) {
    themeToggle.addEventListener("click", toggleTheme);
  }
  initTheme();

  // Filter and pagination event listeners
  if (applyFiltersBtn) {
    applyFiltersBtn.addEventListener("click", applyFilters);
  }
  if (clearFiltersBtn) {
    clearFiltersBtn.addEventListener("click", clearFilters);
  }
  if (prevPageBtn) {
    prevPageBtn.addEventListener("click", () => goToPage(currentPage - 1));
  }
  if (nextPageBtn) {
    nextPageBtn.addEventListener("click", () => goToPage(currentPage + 1));
  }

  dateInput.value = new Date().toISOString().slice(0, 10);
  allowanceInput.value = state.allowance;
  document.querySelector("#goalName").value = state.goal.name;
  document.querySelector("#goalTarget").value = state.goal.target;
  document.querySelector("#goalSaved").value = state.goal.saved;

  // Sync range toggle buttons with state
  syncRangeButtons();
  // Sync custom date inputs with state
  syncCustomDateInputs();

  expenseForm.addEventListener("submit", handleExpenseSubmit);
  goalForm.addEventListener("submit", handleGoalSubmit);
  document.querySelector("#goalName").addEventListener("input", handleGoalInputChange);
  document.querySelector("#goalTarget").addEventListener("input", handleGoalInputChange);
  budgetList.addEventListener("input", handleBudgetInput);
  budgetList.addEventListener("change", handleBudgetChange);
  budgetList.addEventListener("click", handleBudgetClick);
  countrySelect.addEventListener("change", handleCountryChange);
  currencyList.addEventListener("input", handleCurrencyInput);
  currencyList.addEventListener("change", handleCurrencyChange);
  currencyList.addEventListener("click", handleCurrencyRemove);
  addCurrencyButton.addEventListener("click", addSavingsCurrency);
  allowanceInput.addEventListener("input", handleAllowanceChange);
  receiptUpload.addEventListener("change", handleReceiptUpload);
  addScannedExpense.addEventListener("click", handleScannedExpense);
  if (recurringForm) {
    recurringForm.addEventListener("submit", handleRecurringSubmit);
  }
  if (recurringFrequency) {
    recurringFrequency.addEventListener("change", updateRecurringFields);
  }
  updateRecurringFields();
  if (recurringList) {
    recurringList.addEventListener("click", handleRecurringItemClick);
  }
  document.querySelector("#refreshInsights").addEventListener("click", renderInsights);

  // Expense list actions (edit/delete) via delegation
  const expenseListEl = document.querySelector("#expenseList");
  if (expenseListEl) expenseListEl.addEventListener("click", handleExpenseListClick);
  // Recycle bin actions
  const recycleListEl = document.querySelector("#recycleList");
  if (recycleListEl) recycleListEl.addEventListener("click", handleRecycleListClick);

  // Show/hide recycle panel on hash change
  window.addEventListener("hashchange", handleHashChange);
  handleHashChange();

  // Analytics date filtering delegation
  const insightsList = document.querySelector("#insightsList");
  if (insightsList) {
    insightsList.addEventListener("click", async (e) => {
      if (e.target.id === "applyAnalyticsDates") {
        state.analyticsStartDate = document.querySelector("#analyticsStartDate")?.value;
        state.analyticsEndDate = document.querySelector("#analyticsEndDate")?.value;
        await fetchAnalytics();
      }
    });
  }

  // Add another expense button
  const addAnotherBtn = document.querySelector("#addAnotherExpense");
  if (addAnotherBtn) {
    addAnotherBtn.addEventListener("click", handleAddAnotherExpense);
  }
  
  document.querySelector("#exportExpenses")?.addEventListener("click", handleExportExpenses);
  document.querySelector("#emailStatement")?.addEventListener("click", handleEmailStatement);

  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => setRange(button.dataset.range));
  });

  // Custom range inputs event listener
  const applyCustomRangeBtn = document.querySelector("#applyCustomRange");
  if (applyCustomRangeBtn) {
    applyCustomRangeBtn.addEventListener("click", applyCustomRange);
  }

  // Period toggle (weekly/monthly)
  const periodMonthlyBtn = document.querySelector("#periodMonthly");
  const periodWeeklyBtn = document.querySelector("#periodWeekly");
  if (periodMonthlyBtn) {
    periodMonthlyBtn.addEventListener("click", () => setPeriod("monthly"));
  }
  if (periodWeeklyBtn) {
    periodWeeklyBtn.addEventListener("click", () => setPeriod("weekly"));
  }
  // Sync period buttons with state
  syncPeriodButtons();

  renderAuthMode();

  if (!authToken) {
    showAuth();
    return;
  }

  showApp();
  render();
  await hydrateFromApi();
  await fetchAnalytics();
  await autoUpdateGoalSavings();
  render();
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  authMessage.textContent = "";
  toggleLoading(authSubmit, true, authSubmit.textContent);

  try {
    if (authMode === "verify") {
      await verifyEmailCode();
      return;
    }

    const path = authMode === "signup" ? "/api/auth/signup" : "/api/auth/login";
    const payload = {
      email: authEmail.value.trim(),
      password: authPassword.value,
    };
    if (authMode === "signup") {
      payload.first_name = authFirstName.value.trim();
      payload.last_name = authLastName.value.trim();
      payload.gender = authGender.value;
    }

    const data = await apiRequest(path, {
      method: "POST",
      body: JSON.stringify(payload),
      skipAuth: true,
    });

    authToken = data.access_token;
    currentUserEmail = data.profile.email;
    localStorage.setItem(tokenKey, authToken);
    localStorage.setItem(profileEmailKey, currentUserEmail);
    state = loadState(currentUserEmail);
    authPassword.value = "";
    if (!data.profile.email_verified) {
      pendingVerificationEmail = data.profile.email;
      localStorage.setItem(verificationEmailKey, pendingVerificationEmail);
      authMessage.textContent = authMode === "signup"
        ? "We sent a verification code. Check your email or the backend terminal in development."
        : "Verify your email before opening your dashboard.";
      authMode = "verify";
      renderAuthMode();
      showAuth();
      return;
    }

    showApp();
    await hydrateFromApi();
    render();
    showNotification("Logged in successfully", "success");
  } catch (error) {
    showNotification(error.message || "Could not sign in. Check your details and try again.", "error");
  } finally {
    toggleLoading(authSubmit, false, authMode === "verify" ? "Verify account" : (authMode === "signup" ? "Create account" : "Sign in"));
  }
}

function toggleAuthMode() {
  authMode = authMode === "signup" ? "login" : "signup";
  authMessage.textContent = "";
  renderAuthMode();
}

function returnToSignup() {
  authMode = "signup";
  pendingVerificationEmail = "";
  authEmail.readOnly = false;
  authCode.value = "";
  localStorage.removeItem(verificationEmailKey);
  authMessage.textContent = "Update your details, then create the account again.";
  renderAuthMode();
}

function renderAuthMode() {
  const isSignup = authMode === "signup";
  const isVerify = authMode === "verify";
  authTitle.textContent = isVerify ? "Verify email" : isSignup ? "Create account" : "Sign in";
  authSubmit.textContent = isVerify ? "Verify account" : isSignup ? "Create account" : "Sign in";
  authModeToggle.textContent = isSignup ? "I already have an account" : "Create an account";
  authNameField.classList.toggle("hidden", !isSignup);
  authGenderField.classList.toggle("hidden", !isSignup);
  authCodeField.classList.toggle("hidden", !isVerify);
  resendCodeButton.classList.toggle("hidden", !isVerify);
  authBackButton.classList.toggle("hidden", !isVerify);
  authModeToggle.classList.toggle("hidden", isVerify);
  authFirstName.required = isSignup;
  authLastName.required = isSignup;
  authGender.required = isSignup;
  authEmail.readOnly = isVerify;
  authPassword.required = !isVerify;
  authPassword.parentElement.classList.toggle("hidden", isVerify);
  authCode.required = isVerify;
  authPassword.autocomplete = isSignup ? "new-password" : "current-password";
  if (isVerify && pendingVerificationEmail) {
    authEmail.value = pendingVerificationEmail;
  }
}

function showAuth() {
  authScreen.classList.remove("hidden");
  appShell.classList.add("hidden");
}

function showApp() {
  authScreen.classList.add("hidden");
  appShell.classList.remove("hidden");
}

async function logout(event) {
  if (event && event.preventDefault) event.preventDefault();

  // Attempt to tell the backend to revoke refresh tokens (best-effort)
  try {
    await apiRequest("/api/auth/logout", { method: "POST" });
  } catch (e) {
    // ignore network errors — still clear local state
  }

  showNotification("Logged out successfully", "success");

  authToken = null;
  apiOnline = false;
  authMode = "login";
  pendingVerificationEmail = "";
  localStorage.removeItem(tokenKey);
  localStorage.removeItem(profileEmailKey);
  localStorage.removeItem(verificationEmailKey);
  currentUserEmail = "";
  state = loadState(currentUserEmail);
  categories = structuredClone(defaultCategories);
  authMessage.textContent = "";
  renderAuthMode();
  showAuth();
}

async function verifyEmailCode() {
  const data = await apiRequest("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({
      email: authEmail.value.trim(),
      code: authCode.value.trim(),
    }),
    skipAuth: true,
  });

  authToken = data.access_token;
  currentUserEmail = data.profile.email;
  localStorage.setItem(tokenKey, authToken);
  localStorage.setItem(profileEmailKey, currentUserEmail);
  state = loadState(currentUserEmail);
  pendingVerificationEmail = "";
  localStorage.removeItem(verificationEmailKey);
  authCode.value = "";
  authMode = "login";
  renderAuthMode();
  showApp();
  await hydrateFromApi();
  render();
}

async function resendVerificationCode() {
  authMessage.textContent = "";
  resendCodeButton.disabled = true;
  try {
    const data = await apiRequest("/api/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify({ email: authEmail.value.trim() }),
      skipAuth: true,
    });
    authMessage.textContent = data.message;
  } catch (error) {
    authMessage.textContent = error.message || "Could not resend the code.";
  } finally {
    resendCodeButton.disabled = false;
  }
}

async function handleForgotPassword(event) {
  event.preventDefault();
  const email = authEmail.value.trim();

  if (!email) {
    authMessage.textContent = "Please enter your email address first.";
    authEmail.focus();
    return;
  }

  if (!isValidEmail(email)) {
    authMessage.textContent = "Please enter a valid email address.";
    authEmail.focus();
    return;
  }

  authMessage.textContent = "Sending password reset instructions...";
  try {
    const data = await apiRequest("/api/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
      skipAuth: true,
    });
    authMessage.textContent = data.message || "Password reset instructions sent to your email. Check your inbox.";
  } catch (error) {
    authMessage.textContent = error.message || "Could not send reset instructions. Please try again.";
  }
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

async function handleExpenseSubmit(event) {
  event.preventDefault();
  await addExpenseAndRender();
}

async function handleAddAnotherExpense() {
  await addExpenseAndRender();
}

async function addExpenseAndRender() {
  const name = document.querySelector("#expenseName").value.trim();
  const amount = Number(document.querySelector("#expenseAmount").value);
  const category = categorySelect.value;
  const date = dateInput.value;

  // Validate required fields
  if (!name || !amount || !category || !date) {
    showNotification("Please fill in all required fields", "warning");
    return;
  }

  const expensePayload = {
    name,
    amount,
    category,
    date,
  };
  let expense;
  if (editingExpenseId) {
    expensePayload.id = editingExpenseId;
    expense = await updateExpense(editingExpenseId, expensePayload);
    const idx = state.expenses.findIndex((e) => e.id === editingExpenseId);
    if (idx >= 0) state.expenses.splice(idx, 1, expense);
    editingExpenseId = null;
    const submitBtn = document.querySelector("#expenseForm button[type=submit]");
    if (submitBtn) submitBtn.textContent = "Add expense";
  } else {
    expense = await createExpense(expensePayload);
    state.expenses.unshift(expense);
  }
  expenseForm.reset();
  dateInput.value = new Date().toISOString().slice(0, 10);
  categorySelect.value = expense.category;
  persist();
  await autoUpdateGoalSavings();
  maybeShowBudgetNotification(expense, getCategoryTotals(getFilteredExpenses()));
  render();
}

async function handleRecurringSubmit(event) {
  event.preventDefault();
  if (!recurringForm || !recurringName || !recurringAmount || !recurringCategory || !recurringFrequency) return;

  const name = recurringName.value.trim();
  const amount = Number(recurringAmount.value);
  const category = recurringCategory.value || categories[0]?.name || "Other";
  const frequency = recurringFrequency.value;
  const dayOfWeek = frequency === "weekly" ? Number(recurringDayOfWeek.value) : undefined;
  const dayOfMonth = frequency !== "weekly" ? Number(recurringDayOfMonth.value) : undefined;

  if (!name || !amount || !category) {
    showNotification("Please provide a name, amount, and category for the recurring expense.", "warning");
    return;
  }

  const payload = {
    name,
    amount,
    category,
    frequency,
    day_of_week: dayOfWeek,
    day_of_month: dayOfMonth,
  };

  let recurring;
  if (editingRecurringId) {
    recurring = await updateRecurringExpense(editingRecurringId, payload);
  } else {
    recurring = await createRecurringExpense(payload);
  }
  if (recurring) {
    const savedName = recurring.name || category;
    recurringForm.reset();
    recurringFrequency.value = "monthly";
    updateRecurringFields();
    if (recurringForm) {
      recurringForm.querySelector("button[type=submit]").textContent = "Create recurring expense";
    }
    showNotification(
      editingRecurringId
        ? `Recurring expense "${savedName}" updated.`
        : `Recurring expense for ${savedName} has been scheduled.`,
      "success",
    );
    editingRecurringId = null;
    await fetchRecurringExpenses();
    renderRecurringExpenses();
  }
}

async function updateRecurringExpense(id, payload) {
  if (!apiOnline) return null;
  try {
    const saved = await apiRequest(`/api/recurring-expenses/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    return normalizeRecurringExpense(saved);
  } catch {
    apiOnline = false;
    return null;
  }
}

async function deleteRecurringExpense(id) {
  if (!apiOnline) return false;
  try {
    await apiRequest(`/api/recurring-expenses/${id}`, {
      method: "DELETE",
    });
    return true;
  } catch {
    apiOnline = false;
    return false;
  }
}

function handleRecurringItemClick(event) {
  const editButton = event.target.closest("button[data-recurring-edit]");
  const deleteButton = event.target.closest("button[data-recurring-delete]");
  if (editButton) {
    const recurringId = Number(editButton.dataset.recurringEdit);
    const recurring = state.recurringExpenses?.find((item) => item.id === recurringId);
    if (!recurring) return;
    editingRecurringId = recurringId;
    recurringName.value = recurring.name;
    recurringAmount.value = recurring.amount;
    recurringCategory.value = recurring.category;
    recurringFrequency.value = recurring.frequency;
    recurringDayOfMonth.value = recurring.day_of_month || 1;
    recurringDayOfWeek.value = recurring.day_of_week || 0;
    updateRecurringFields();
    if (recurringForm) {
      recurringForm.querySelector("button[type=submit]").textContent = "Save recurring expense";
    }
    showNotification("Editing recurring expense. Save to apply changes.", "info");
    return;
  }
  if (deleteButton) {
    const recurringId = Number(deleteButton.dataset.recurringDelete);
    handleDeleteRecurringExpense(recurringId);
    return;
  }
}

async function handleDeleteRecurringExpense(id) {
  if (!window.confirm("Delete this recurring expense? This cannot be undone.")) return;
  const success = await deleteRecurringExpense(id);
  if (success) {
    state.recurringExpenses = state.recurringExpenses.filter((item) => item.id !== id);
    renderRecurringExpenses();
    showNotification("Recurring expense removed.", "success");
  } else {
    showNotification("Could not delete recurring expense.", "error");
  }
}

async function updateExpense(id, payload) {
  if (!apiOnline) return { ...payload, id };
  try {
    const saved = await apiRequest(`/api/expenses/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    return normalizeExpense(saved);
  } catch {
    apiOnline = false;
    return { ...payload, id };
  }
}

async function handleExportExpenses() {
  try {
    const response = await fetch(`${apiBase}/api/expenses/export`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (!response.ok) throw new Error("Export failed");
    
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `student_expenses_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (err) {
    showNotification("Failed to export expenses. Please try again.", "error");
  }
}

async function handleEmailStatement() {
  try {
    const response = await apiRequest("/api/expenses/export/email", {
      method: "POST",
      body: JSON.stringify({ email: state.profile.email }),
    });
    showNotification(response.message || "Expense statement emailed successfully", "success");
  } catch (err) {
    showNotification("Could not send the statement email. Please try again.", "error");
  }
}

async function deleteExpense(id) {
  if (!apiOnline) {
    state.expenses = state.expenses.filter((e) => e.id !== id);
    persist();
    render();
    return;
  }

  try {
    // Soft-delete by moving to recycle bin
    await softDeleteExpense(id);
  } catch {
    apiOnline = false;
  }
}

async function softDeleteExpense(id) {
  if (!apiOnline) {
    const idx = state.expenses.findIndex((e) => e.id === id);
    if (idx >= 0) {
      state.expenses[idx].deleted = true;
      state.expenses[idx].deleted_at = new Date().toISOString();
      // remove from active list
      state.expenses.splice(idx, 1);
      persist();
      render();
    }
    return;
  }

  try {
    const saved = await apiRequest(`/api/expenses/${id}/delete`, { method: "PATCH" });
    state.expenses = state.expenses.filter((e) => e.id !== id);
    persist();
    showSessionMessage("Moved to recycle bin", 3000);
    await loadRecycleBin();
    render();
  } catch (err) {
    throw err;
  }
}

async function restoreExpense(id) {
  if (!apiOnline) {
    showNotification("Cannot restore while offline.", "warning");
    return;
  }

  try {
    const restored = await apiRequest(`/api/expenses/${id}/restore`, { method: "POST" });
    state.expenses.unshift(normalizeExpense(restored));
    persist();
    await loadRecycleBin();
    render();
    showNotification("Expense restored", "success");
  } catch (err) {
    apiOnline = false;
  }
}

async function permanentlyDeleteExpense(id) {
  if (!apiOnline) {
    showNotification("Cannot permanently delete while offline.", "warning");
    return;
  }

  try {
    await apiRequest(`/api/expenses/${id}`, { method: "DELETE" });
    await loadRecycleBin();
    showNotification("Expense permanently deleted", "success");
  } catch (err) {
    apiOnline = false;
  }
}

async function loadRecycleBin(page = 1, per_page = 50) {
  if (!apiOnline) return;
  try {
    const params = new URLSearchParams({ page, per_page });
    const data = await apiRequest(`/api/expenses/recycle?${params.toString()}`);
    // data.expenses is expected
    const items = (data.expenses || []).map(normalizeExpense);
    renderRecycleBin(items);
  } catch (err) {
    apiOnline = false;
  }
}

function renderRecycleBin(items) {
  const list = document.querySelector("#recycleList");
  if (!items || items.length === 0) {
    list.innerHTML = `<div class="expense-item"><strong>Recycle bin empty</strong><span>No deleted expenses.</span></div>`;
    return;
  }

  list.innerHTML = items
    .map(
      (expense) => `
        <article class="expense-item">
          <strong>${expense.name}<span>${formatMoney(expense.amount)}</span></strong>
          <span>${expense.category} · ${formatDate(expense.date)} · deleted ${expense.deleted_at ? new Date(expense.deleted_at).toLocaleString() : ''}</span>
          <div class="expense-actions">
            <button class="text-button restore-expense" data-id="${expense.id}" type="button">Restore</button>
            <button class="text-button permanent-delete" data-id="${expense.id}" type="button">Delete permanently</button>
          </div>
        </article>
      `,
    )
    .join("");
}

function handleRecycleListClick(e) {
  const restoreBtn = e.target.closest(".restore-expense");
  const permBtn = e.target.closest(".permanent-delete");
  if (restoreBtn) {
    const id = Number(restoreBtn.dataset.id);
    restoreExpense(id);
    return;
  }
  if (permBtn) {
    const id = Number(permBtn.dataset.id);
    if (!confirm("Permanently delete this expense? This cannot be undone.")) return;
    permanentlyDeleteExpense(id);
    return;
  }
}

function handleExpenseListClick(e) {
  const editBtn = e.target.closest(".edit-expense");
  const delBtn = e.target.closest(".delete-expense");
  if (editBtn) {
    const id = Number(editBtn.dataset.id);
    const expense = state.expenses.find((ex) => ex.id === id);
    if (!expense) return;
    document.querySelector("#expenseName").value = expense.name;
    document.querySelector("#expenseAmount").value = expense.amount;
    document.querySelector("#expenseCategory").value = expense.category;
    document.querySelector("#expenseDate").value = expense.date;
    editingExpenseId = id;
    const submitBtn = document.querySelector("#expenseForm button[type=submit]");
    if (submitBtn) submitBtn.textContent = "Save";
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }

  if (delBtn) {
    const id = Number(delBtn.dataset.id);
    if (!confirm("Delete this expense? This cannot be undone.")) return;
    deleteExpense(id);
    return;
  }
}

function handleBudgetClick(e) {
  const presetBtn = e.target.closest(".preset-btn");
  if (!presetBtn) return;
  const index = Number(presetBtn.dataset.presetIndex);
  const raw = presetBtn.dataset.presetPercent;
  if (raw === "custom") {
    // focus the limit input for manual entry
    const input = budgetList.querySelector(`[data-budget-index="${index}"]`);
    if (input) input.focus();
    return;
  }
  const percent = Number(raw) || 0;
  if (!Number.isInteger(index) || !categories[index]) return;
  const value = Math.round((state.allowance || 0) * (percent / 100));
  categories[index].budget = Math.max(0, Math.min(1e9, value));
  persistCategories();
  saveCategoryBudget(index);
  render();
}

async function autoUpdateGoalSavings() {
  syncGoalSavingsFromSpending();
  if (!state.goal.name || state.goal.target < 1) return;

  state.goal = await updateGoal(state.goal);
  document.querySelector("#goalSaved").value = state.goal.saved;
  persist();
}

function syncGoalSavingsFromSpending() {
  const availableSavings = calculateAvailableSavings();
  if (availableSavings === state.goal.saved) return false;

  state.goal.saved = availableSavings;
  document.querySelector("#goalSaved").value = state.goal.saved;
  persist();
  return true;
}

function calculateAvailableSavings() {
  if (state.allowance <= 0 || state.goal.target <= 0) return 0;

  const filtered = getFilteredExpenses();
  const totalSpent = sum(filtered.map((expense) => expense.amount));
  const remainingAllowance = Math.max(0, state.allowance - totalSpent);
  return Math.min(Math.round(remainingAllowance), state.goal.target);
}

async function handleGoalSubmit(event) {
  event.preventDefault();
  clearTimeout(goalSaveTimer);
  await saveGoalFromInputs();
}

function handleGoalInputChange() {
  syncGoalFromInputs();
  syncGoalSavingsFromSpending();
  persist();
  render();
  clearTimeout(goalSaveTimer);
  goalSaveTimer = setTimeout(saveGoalFromInputs, 450);
}

function syncGoalFromInputs() {
  state.goal = {
    name: document.querySelector("#goalName").value.trim(),
    target: Math.max(0, Math.min(Number(document.querySelector("#goalTarget").value) || 0, 1e9)),
    saved: Number(document.querySelector("#goalSaved").value) || 0,
  };
}

async function saveGoalFromInputs() {
  syncGoalFromInputs();
  syncGoalSavingsFromSpending();
  if (!state.goal.name || state.goal.target < 1) {
    persist();
    render();
    return;
  }

  state.goal = await updateGoal(state.goal);
  document.querySelector("#goalName").value = state.goal.name;
  document.querySelector("#goalTarget").value = state.goal.target;
  document.querySelector("#goalSaved").value = state.goal.saved;
  persist();
  render();
}

function handleAllowanceChange() {
  state.allowance = Number(allowanceInput.value) || 0;
  syncGoalSavingsFromSpending();
  persist();
  render();
  clearTimeout(profileSaveTimer);
  profileSaveTimer = setTimeout(() => {
    updateProfile(state.allowance);
    autoUpdateGoalSavings();
  }, 350);
}

function handleRangeChange(range) {
  state.range = range;
  syncRangeButtons();
  persist();
  render();
  // Sync with backend if online
  if (apiOnline && range === "custom") {
    updateProfileRange(state.allowance, range, state.customStartDate, state.customEndDate);
  } else if (apiOnline) {
    updateProfileRange(state.allowance, range, null, null);
  }
}

async function updateProfileRange(allowance, preferredRange, customStart, customEnd) {
  if (!apiOnline) return;
  try {
    await apiRequest("/api/profile", {
      method: "PATCH",
      body: JSON.stringify({
        allowance,
        preferred_range: preferredRange,
        custom_range_start: customStart,
        custom_range_end: customEnd,
      }),
    });
  } catch {
    apiOnline = false;
  }
}

async function handleReceiptUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = () => {
    document.querySelector("#receiptPreview").innerHTML = `<img src="${reader.result}" alt="Uploaded receipt preview" />`;
  };
  reader.readAsDataURL(file);

  document.querySelector("#scanResult").innerHTML = `
    <strong>Scanning receipt...</strong>
    <span>Looking for merchant, total amount, and category.</span>
  `;
  addScannedExpense.disabled = true;

  scannedExpense = await scanReceipt(file);
  document.querySelector("#scanResult").innerHTML = `
    <strong>${scannedExpense.name} · ${formatMoney(scannedExpense.amount)}</strong>
    <span>${scannedExpense.category} detected from ${scannedExpense.source}, dated ${formatDate(scannedExpense.date)}.</span>
  `;
  addScannedExpense.disabled = false;
}

async function handleScannedExpense() {
  if (!scannedExpense) return;
  try {
    const created = await createExpense({
      name: scannedExpense.name,
      amount: scannedExpense.amount,
      category: scannedExpense.category,
      date: scannedExpense.date,
    });
    if (created) {
      state.expenses.unshift(created);
      persist();
      render();
      showNotification(`Scanned receipt added as ${created.category} expense.`, "success");
    } else {
      throw new Error("Add scanned expense failed");
    }
  } catch (error) {
    showNotification("Auto-add failed. Please review the receipt values manually.", "warning");
    document.querySelector("#expenseName").value = scannedExpense.name;
    document.querySelector("#expenseAmount").value = scannedExpense.amount;
    document.querySelector("#expenseCategory").value = scannedExpense.category;
    document.querySelector("#expenseDate").value = scannedExpense.date;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  scannedExpense = null;
  addScannedExpense.disabled = true;
  receiptUpload.value = "";
}

function setRange(range) {
  state.range = range;
  syncRangeButtons();
  syncGoalSavingsFromSpending();
  persist();
  render();
  autoUpdateGoalSavings();
}

function syncRangeButtons() {
  const customInputs = document.querySelector("#customRangeInputs");
  document.querySelectorAll("[data-range]").forEach((button) => {
    const isActive = button.dataset.range === state.range;
    button.classList.toggle("active", isActive);
  });
  // Show/hide custom date inputs
  if (customInputs) {
    customInputs.classList.toggle("hidden", state.range !== "custom");
  }
}

function syncCustomDateInputs() {
  const startInput = document.querySelector("#customStartDate");
  const endInput = document.querySelector("#customEndDate");
  if (startInput) startInput.value = state.customStartDate;
  if (endInput) endInput.value = state.customEndDate;
}

function applyCustomRange() {
  const startInput = document.querySelector("#customStartDate");
  const endInput = document.querySelector("#customEndDate");
  if (!startInput || !endInput) return;

  const startDate = startInput.value;
  const endDate = endInput.value;

  if (!startDate || !endDate) {
    alert("Please select both start and end dates");
    return;
  }

  if (new Date(startDate) > new Date(endDate)) {
    alert("Start date must be before end date");
    return;
  }

  state.customStartDate = startDate;
  state.customEndDate = endDate;
  state.range = "custom";
  syncRangeButtons();
  syncGoalSavingsFromSpending();
  persist();
  render();
  autoUpdateGoalSavings();
}

function setPeriod(period) {
  state.period = period;
  syncPeriodButtons();

  const allowancePeriodLabel = document.querySelector("#allowancePeriodLabel");
  if (allowancePeriodLabel) {
    allowancePeriodLabel.textContent = period === "monthly" ? "Monthly allowance" : "Weekly allowance";
  }

  persist();
  render();
  autoUpdateGoalSavings();
}

function syncPeriodButtons() {
  const periodMonthlyBtn = document.querySelector("#periodMonthly");
  const periodWeeklyBtn = document.querySelector("#periodWeekly");
  
  if (periodMonthlyBtn) {
    const isMonthly = state.period === "monthly";
    periodMonthlyBtn.classList.toggle("active", isMonthly);
    periodMonthlyBtn.style.background = isMonthly ? "#4CAF50" : "transparent";
    periodMonthlyBtn.style.color = isMonthly ? "white" : "#666";
  }
  
  if (periodWeeklyBtn) {
    const isWeekly = state.period === "weekly";
    periodWeeklyBtn.classList.toggle("active", isWeekly);
    periodWeeklyBtn.style.background = isWeekly ? "#4CAF50" : "transparent";
    periodWeeklyBtn.style.color = isWeekly ? "white" : "#666";
  }
  
  // Update allowance label
  const allowancePeriodLabel = document.querySelector("#allowancePeriodLabel");
  if (allowancePeriodLabel) {
    allowancePeriodLabel.textContent = state.period === "monthly" ? "Monthly allowance" : "Weekly allowance";
  }
}

function render() {
  renderCategoryOptions();
  syncGoalSavingsFromSpending();
  const filtered = getFilteredExpenses();
  const totals = getCategoryTotals(filtered);
  const totalSpent = sum(filtered.map((expense) => expense.amount));
  const totalBudget = sum(categories.map((category) => category.budget));
  const top = Object.entries(totals).sort((a, b) => b[1] - a[1])[0];
  const goalPercent = state.goal.target > 0
    ? Math.min(100, Math.round((state.goal.saved / state.goal.target) * 100) || 0)
    : 0;

  renderGreeting();
  document.querySelector("#allowanceLabel").textContent = formatMoney(state.allowance);
  document.querySelector("#totalSpent").textContent = formatMoney(totalSpent);
  document.querySelector("#spentCaption").textContent = `This ${state.range}`;
  document.querySelector("#budgetLeft").textContent = formatMoney(Math.max(0, totalBudget - totalSpent));
  document.querySelector("#savingsProgress").textContent = `${goalPercent}%`;
  document.querySelector("#topCategory").textContent = top ? top[0] : "None";
  document.querySelector("#topCategoryCaption").textContent = top
    ? `${Math.round((top[1] / Math.max(totalSpent, 1)) * 100)}% of ${state.range} spending`
    : "Add expenses to learn";

  renderHealthScore(totals, totalSpent);
  renderBudgetWarnings(totals);

  renderNetWorth();

  renderRecurringExpenses();
  renderCategoryBars(totals, totalSpent);
  renderExpenses(filtered);
  renderBudgets(totals);
  renderGoal(goalPercent, totalSpent);
  renderCurrencyControls(); // This now includes Total Balance logic via fetchAnalytics calls
  renderInsights();
}

function renderCategoryOptions() {
  const selected = categorySelect.value;
  categorySelect.innerHTML = categories
    .map((category) => `<option value="${category.name}">${category.name}</option>`)
    .join("");
  if (selected && categories.some((category) => category.name === selected)) {
    categorySelect.value = selected;
  }
  if (recurringCategory) {
    const current = recurringCategory.value;
    recurringCategory.innerHTML = categories
      .map((category) => `<option value="${category.name}">${category.name}</option>`)
      .join("");
    if (current && categories.some((category) => category.name === current)) {
      recurringCategory.value = current;
    }
  }
}
async function fetchRecurringExpenses() {
  if (!apiOnline) return;
  try {
    const data = await apiRequest("/api/recurring-expenses");
    state.recurringExpenses = Array.isArray(data) ? data.map(normalizeRecurringExpense) : [];
  } catch {
    state.recurringExpenses = [];
  }
}

function renderRecurringExpenses() {
  if (!recurringList) return;
  const items = state.recurringExpenses || [];
  if (!items.length) {
    recurringList.innerHTML = `<div class="expense-item"><strong>No recurring expenses set.</strong><span>Create a weekly, monthly, or yearly payment to stay on track.</span></div>`;
    return;
  }

  recurringList.innerHTML = items
    .map((item) => {
      const schedule = item.frequency === "weekly"
        ? `Every ${["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][item.day_of_week]}`
        : item.frequency === "monthly"
          ? `Day ${item.day_of_month} of each month`
          : `Day ${item.day_of_month} of each year`;
      const lastGenerated = item.last_generated_at
        ? `<span class="muted">Last run ${new Date(item.last_generated_at).toLocaleDateString()}</span>`
        : "";
      return `
        <article class="expense-item">
          <div>
          <strong>${item.name}<span>${formatMoney(item.amount)}</span></strong>
          <span>${item.category} · ${schedule}</span>
          ${lastGenerated}
          </div>
          <div class="recurring-actions">
            <button class="secondary-button" type="button" data-recurring-edit="${item.id}">Edit</button>
            <button class="danger-button" type="button" data-recurring-delete="${item.id}">Delete</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function normalizeRecurringExpense(recurring) {
  return {
    id: recurring.id,
    name: recurring.name,
    amount: Number(recurring.amount),
    category: recurring.category,
    frequency: recurring.frequency,
    day_of_month: recurring.day_of_month,
    day_of_week: recurring.day_of_week,
    last_generated_at: recurring.last_generated_at || null,
  };
}

function updateRecurringFields() {
  if (!recurringFrequency || !recurringDayOfWeek || !recurringDayOfMonth) return;
  const weekly = recurringFrequency.value === "weekly";
  recurringDayOfWeek.closest("label")?.classList.toggle("hidden", !weekly);
  recurringDayOfMonth.closest("label")?.classList.toggle("hidden", weekly);
}

function getBudgetWarnings(totals) {
  return categories.reduce((warnings, category) => {
    if (!category.budget) return warnings;
    const spent = totals[category.name] || 0;
    const percent = Math.round((spent / category.budget) * 100);
    if (percent >= 100) {
      warnings.push(`You’ve exceeded your ${category.name} budget by ${formatMoney(spent - category.budget)}.`);
    } else if (percent >= 90) {
      warnings.push(`You’ve used ${percent}% of your ${category.name} budget.`);
    }
    return warnings;
  }, []);
}

function renderBudgetWarnings(totals) {
  const warningEl = document.querySelector("#budgetWarning");
  if (!warningEl) return;
  const warnings = getBudgetWarnings(totals);
  if (warnings.length) {
    warningEl.classList.remove("hidden");
    warningEl.textContent = warnings[0];
    return;
  }
  const totalBudget = sum(categories.map((category) => category.budget));
  if (state.allowance > 0 && totalBudget > state.allowance) {
    warningEl.classList.remove("hidden");
    warningEl.textContent = "Warning: total category budgets exceed your allowance.";
    return;
  }
  warningEl.classList.add("hidden");
}

function calculateHealthScore(totals, totalSpent) {
  const spendingScore = state.allowance > 0
    ? Math.max(0, Math.min(100, Math.round(100 - Math.min(100, (totalSpent / state.allowance) * 100) * 0.6)))
    : 60;
  const savingsScore = state.goal.target > 0
    ? Math.min(100, Math.round((state.goal.saved / state.goal.target) * 100))
    : 50;
  const budgetCategories = categories.filter((category) => category.budget > 0);
  const disciplineScore = budgetCategories.length
    ? Math.round(
        (budgetCategories.filter((category) => (totals[category.name] || 0) <= category.budget).length / budgetCategories.length) * 100,
      )
    : 75;
  return Math.round(spendingScore * 0.4 + savingsScore * 0.35 + disciplineScore * 0.25);
}

function healthRating(score) {
  if (score >= 80) return "Good";
  if (score >= 55) return "Fair";
  return "Poor";
}

function renderHealthScore(totals, totalSpent) {
  const score = calculateHealthScore(totals, totalSpent);
  const label = healthRating(score);
  const healthEl = document.querySelector("#healthScore");
  const captionEl = document.querySelector("#healthCaption");
  if (healthEl) healthEl.textContent = `${score}/100`;
  if (captionEl) captionEl.textContent = `${label} financial health`; 
}

function maybeShowBudgetNotification(expense, totals) {
  if (!expense || !expense.category) return;
  const category = categories.find((item) => item.name === expense.category);
  if (!category || !category.budget) return;
  const spent = totals[category.name] || 0;
  const percent = Math.round((spent / category.budget) * 100);
  if (percent >= 90) {
    showNotification(`You’ve used ${percent}% of your ${category.name} budget.`, "warning");
  }
}

function renderCategoryBars(totals, totalSpent) {
  document.querySelector("#categoryBars").innerHTML = categories
    .map((category) => {
      const amount = totals[category.name] || 0;
      const width = Math.round((amount / Math.max(totalSpent, 1)) * 100);
      return `
        <div class="bar-row">
          <strong>${category.name}</strong>
          <div class="track"><div class="fill" style="--width:${width}%;--color:${category.color}"></div></div>
          <span>${formatMoney(amount)}</span>
        </div>
      `;
    })
    .join("");
}

function renderExpenses(expenses) {
  const list = document.querySelector("#expenseList");
  if (!expenses.length) {
    list.innerHTML = `<div class="expense-item"><strong>No expenses yet</strong><span>Add one to start tracking.</span></div>`;
    return;
  }

  // Show all expenses from current page (not just first 8)
  list.innerHTML = expenses
    .map(
      (expense) => `
        <article class="expense-item">
          <strong>${expense.name}<span>${formatMoney(expense.amount)}</span></strong>
          <span>${expense.category} · ${formatDate(expense.date)}</span>
          <div class="expense-actions">
            <button class="text-button edit-expense" data-id="${expense.id}" type="button">Edit</button>
            <button class="text-button delete-expense" data-id="${expense.id}" type="button">Delete</button>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderBudgets(totals) {
  budgetList.innerHTML = categories
    .map((category, index) => {
      const spent = totals[category.name] || 0;
      const hasBudget = category.budget > 0;
      const percent = hasBudget ? Math.round((spent / category.budget) * 100) : 0;
      const status = hasBudget && percent > 100 ? "danger" : hasBudget && percent > 80 ? "warning" : "";
      return `
        <article class="budget-item ${status}">
          <strong>${category.name}<span>${formatMoney(spent)} / ${formatMoney(category.budget)}</span></strong>
          <div class="budget-progress">
            <div class="track"><div class="fill" style="--width:${Math.min(percent, 100)}%;--color:${category.color}"></div></div>
            <span>${hasBudget ? `${percent}%` : "Not set"}</span>
          </div>
          <div class="budget-presets">
            <button type="button" class="preset-btn" data-preset-index="${index}" data-preset-percent="10">10%</button>
            <button type="button" class="preset-btn" data-preset-index="${index}" data-preset-percent="20">20%</button>
            <button type="button" class="preset-btn" data-preset-index="${index}" data-preset-percent="custom">Custom</button>
          </div>
          <label class="budget-limit">
            Limit
            <input
              type="number"
              min="0"
              step="1"
              value="${category.budget}"
              data-budget-index="${index}"
              aria-label="${category.name} budget limit"
            />
          </label>
        </article>
      `;
    })
    .join("");
}

function handleBudgetInput(event) {
  if (!event.target.matches("[data-budget-index]")) return;

  const index = Number(event.target.dataset.budgetIndex);
  if (!Number.isInteger(index) || !categories[index]) return;
  let val = Number(event.target.value);
  if (!Number.isFinite(val)) val = 0;
  // Prevent negative or absurd values
  val = Math.max(0, Math.min(val, 1e9));
  categories[index].budget = val;
  // reflect sanitized value back to input
  event.target.value = val;
  persistCategories();
  updateBudgetSummary();

  clearTimeout(budgetSaveTimers.get(index));
  budgetSaveTimers.set(index, setTimeout(() => saveCategoryBudget(index), 500));
}

async function handleBudgetChange(event) {
  if (!event.target.matches("[data-budget-index]")) return;

  const index = Number(event.target.dataset.budgetIndex);
  if (!Number.isInteger(index) || !categories[index]) return;

  clearTimeout(budgetSaveTimers.get(index));
  await saveCategoryBudget(index);
  render();
}

async function saveCategoryBudget(index) {
  const category = categories[index];
  if (!category) return;

  const savedCategory = await updateCategoryBudget(category);
  categories[index] = savedCategory;
  persistCategories();
}

function updateBudgetSummary() {
  const filtered = getFilteredExpenses();
  const totalSpent = sum(filtered.map((expense) => expense.amount));
  const totalBudget = sum(categories.map((category) => category.budget));
  document.querySelector("#budgetLeft").textContent = formatMoney(Math.max(0, totalBudget - totalSpent));
  const warningEl = document.querySelector("#budgetWarning");
  if (warningEl) {
    if (state.allowance > 0 && totalBudget > state.allowance) {
      warningEl.classList.remove("hidden");
      warningEl.textContent = "Warning: total category budgets exceed your allowance.";
    } else {
      warningEl.classList.add("hidden");
    }
  }
}

function renderCurrencyControls() {
  countrySelect.innerHTML = Object.keys(currencyConfig)
    .map((country) => `<option value="${country}">${country} (${currencyConfig[country].code})</option>`)
    .join("");
  countrySelect.value = state.country || "United States";

  const currencies = normalizeSavingsCurrencies();
  currencyList.innerHTML = currencies
    .map((entry, index) => `
      <div class="currency-wallet">
        <div class="wallet-main">
          <select data-currency-index="${index}" data-currency-field="currency" aria-label="Wallet currency">
            ${currencyOptions(entry.currency)}
          </select>
          <input
            type="number"
            min="0"
            step="0.01"
            value="${entry.amount}"
            data-currency-index="${index}"
            data-currency-field="amount"
            aria-label="${entry.currency} wallet amount"
          />
          <button class="icon-button" type="button" data-remove-currency="${index}" aria-label="Remove wallet">×</button>
        </div>
        <input
          type="text"
          value="${escapeHtml(entry.purpose)}"
          data-currency-index="${index}"
          data-currency-field="purpose"
          placeholder="Purpose, e.g. Travel, dorm supplies"
          aria-label="${entry.currency} wallet purpose"
        />
        <strong>${formatMoneyInCurrency(entry.amount, entry.currency)} saved${entry.purpose ? ` for ${escapeHtml(entry.purpose)}` : ""}</strong>
      </div>
    `)
    .join("");

  // Show a simple wallet total summary grouped by currency
  const totals = currencies.reduce((acc, entry) => {
    acc[entry.currency] = (acc[entry.currency] || 0) + Number(entry.amount || 0);
    return acc;
  }, {});

  const walletTotalEl = document.querySelector("#walletTotal");
  if (walletTotalEl) {
    const parts = Object.entries(totals).map(([cur, amt]) => `${formatMoneyInCurrency(amt, cur)}`);
    walletTotalEl.textContent = parts.join(" • ") || formatMoney(0);
  }

  // Show converted total balance if available
  const totalConvertedEl = document.querySelector("#totalConvertedBalance");
  if (totalConvertedEl && state.totalConvertedBalance) {
    totalConvertedEl.textContent = `Total Net Worth: ${formatMoney(state.totalConvertedBalance.total_converted_balance, state.totalConvertedBalance.home_currency)}`;
    totalConvertedEl.classList.remove("hidden");
  } else if (totalConvertedEl) {
    totalConvertedEl.classList.add("hidden");
  }
}

async function fetchAnalytics() {
  if (!apiOnline) return;
  try {
    const query = new URLSearchParams();
    if (state.analyticsStartDate) query.set("start_date", state.analyticsStartDate);
    if (state.analyticsEndDate) query.set("end_date", state.analyticsEndDate);
    const categoryAnalytics = await apiRequest(`/api/analytics/categories?${query.toString()}`);
    state.categoryAnalytics = Array.isArray(categoryAnalytics) ? categoryAnalytics : [];
  } catch {
    state.categoryAnalytics = [];
  }

  try {
    const totalBalance = await apiRequest("/api/analytics/total-balance");
    state.totalConvertedBalance = totalBalance || null;
  } catch {
    state.totalConvertedBalance = null;
  }
}

function renderNetWorth() {
  const netWorthEl = document.querySelector("#netWorth");
  if (!netWorthEl) return;
  const balanceValue = state.totalConvertedBalance?.total_converted_balance || 0;
  const savingsValue = Number(state.goal?.saved || 0);
  const netWorthTotal = balanceValue + savingsValue;
  const currencyCode = state.totalConvertedBalance?.home_currency || currencyConfig[state.country]?.code || "USD";
  netWorthEl.textContent = formatMoneyInCurrency(netWorthTotal, currencyCode);
}

function handleCountryChange() {
  state.country = countrySelect.value;
  persist();
  render();
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(saveSettingsToServer, 500);
}

function handleCurrencyInput(event) {
  const index = Number(event.target.dataset.currencyIndex);
  const field = event.target.dataset.currencyField;
  if (!Number.isInteger(index) || !field) return;

  const currencies = normalizeSavingsCurrencies();
  if (!currencies[index]) return;

  currencies[index][field] = field === "amount" ? Number(event.target.value) || 0 : event.target.value.trim();
  state.savingsCurrencies = currencies;
  persist();
  // Simple validation: if amount > 0 ensure purpose is not blank
  if (currencies[index].amount > 0 && !currencies[index].purpose) {
    showNotification("Consider adding a purpose for this wallet.", "info");
  }
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(saveSettingsToServer, 500);
}

function handleCurrencyChange(event) {
  if (!event.target.dataset.currencyIndex) return;
  handleCurrencyInput(event);
  render();
}

function handleCurrencyRemove(event) {
  const index = Number(event.target.dataset.removeCurrency);
  if (!Number.isInteger(index)) return;

  const currencies = normalizeSavingsCurrencies();
  currencies.splice(index, 1);
  state.savingsCurrencies = currencies.length ? currencies : [{ currency: currentCountryCurrency(), amount: 0, purpose: "" }];
  persist();
  render();
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(saveSettingsToServer, 500);
}

function addSavingsCurrency() {
  const currencies = normalizeSavingsCurrencies();
  currencies.push({ currency: currentCountryCurrency(), amount: 0, purpose: "" });
  state.savingsCurrencies = currencies;
  persist();
  render();
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(saveSettingsToServer, 500);
}

function renderGoal(goalPercent, totalSpent) {
  const target = Number(state.goal.target) || 0;
  const leftAfterSpending = Math.max(0, Number(state.allowance || 0) - Number(totalSpent || 0));
  // Available toward goal is how much of leftAfterSpending can be applied to the goal's remaining need
  const stillNeeded = Math.max(0, target - (Number(state.goal.saved) || 0));
  const availableTowardGoal = Math.min(leftAfterSpending, stillNeeded);
  const surplusAfterGoal = Math.max(0, (Number(state.goal.saved) || 0) - target);

  document.querySelector("#goalNameLabel").textContent = state.goal.name;
  document.querySelector("#goalSavedLabel").textContent = formatMoney(leftAfterSpending);
  document.querySelector("#goalSpentLabel").textContent = formatMoney(totalSpent);
  document.querySelector("#goalRemainingLabel").textContent = formatMoney(stillNeeded);
  document.querySelector("#goalTargetLabel").textContent = formatMoney(target);
  const surplusEl = document.querySelector("#goalSurplusLabel");
  if (surplusEl) surplusEl.textContent = formatMoney(surplusAfterGoal);

  document.querySelector("#goalProgressLabel").textContent = buildGoalProgressText(availableTowardGoal, stillNeeded, target, goalPercent);
  document.querySelector("#goalFormulaLabel").textContent =
    `${formatMoney(state.allowance)} allowance - ${formatMoney(totalSpent)} spent = ${formatMoney(leftAfterSpending)} left`;

  drawSavingsPieChart(availableTowardGoal, stillNeeded, target);
}

function buildGoalProgressText(availableTowardGoal, remaining, target, goalPercent) {
  if (target <= 0) return "Set a savings target to start forecasting.";
  if (availableTowardGoal >= target || remaining <= 0) return `On track: this ${formatMoney(target)} goal can be covered.`;
  if (availableTowardGoal <= 0) return `No available funds left after spending for this ${state.range}.`;
  return `${goalPercent}% covered. ${formatMoney(availableTowardGoal)} available toward goal; still need ${formatMoney(remaining)}.`;
}

function drawSavingsPieChart(saved, remaining, target) {
  const canvas = document.getElementById("savingsChart");
  if (!canvas) return;
  
  const ctx = canvas.getContext("2d");
  const size = Math.min(canvas.clientWidth || canvas.width, canvas.clientHeight || canvas.height);
  const scale = window.devicePixelRatio || 1;
  if (canvas.width !== size * scale || canvas.height !== size * scale) {
    canvas.width = size * scale;
    canvas.height = size * scale;
  }
  ctx.setTransform(scale, 0, 0, scale, 0, 0);

  const centerX = size / 2;
  const centerY = size / 2;
  const radius = (size / 2) - 8;
  const innerRadius = radius * 0.58;
  const savedRatio = target > 0 ? Math.min(Math.max(saved / target, 0), 1) : 0;
  const percent = Math.round(savedRatio * 100);
  const startAngle = -Math.PI / 2;
  const endAngle = startAngle + (savedRatio * 2 * Math.PI);

  ctx.clearRect(0, 0, size, size);

  ctx.beginPath();
  ctx.arc(centerX, centerY, radius, 0, 2 * Math.PI);
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--line").trim() || "#e0e0e0";
  ctx.fill();

  if (target <= 0) {
    ctx.beginPath();
    ctx.arc(centerX, centerY, innerRadius, 0, 2 * Math.PI);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--panel").trim() || "#ffffff";
    ctx.fill();
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#666666";
    ctx.font = "700 13px Inter, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("Set goal", centerX, centerY);
    return;
  }

  if (savedRatio > 0) {
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.arc(centerX, centerY, radius, startAngle, endAngle);
    ctx.closePath();
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--green").trim() || "#159947";
    ctx.fill();
  }

  ctx.beginPath();
  ctx.arc(centerX, centerY, innerRadius, 0, 2 * Math.PI);
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--panel").trim() || "#ffffff";
  ctx.fill();

  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--ink").trim() || "#333333";
  ctx.font = "800 28px Inter, Arial, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(`${percent}%`, centerX, centerY - 8);

  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#666666";
  ctx.font = "700 12px Inter, Arial, sans-serif";
  ctx.fillText("saved", centerX, centerY + 18);
}

function renderInsights() {
  const filtered = getFilteredExpenses();
  const totals = getCategoryTotals(filtered);
  const totalSpent = sum(filtered.map((expense) => expense.amount));
  const insights = buildInsights(totals, totalSpent);
  
  let html = insights
    .map(
      (insight) => `
        <article class="insight">
          <strong>${insight.title}</strong>
          <span>${insight.body}</span>
        </article>
      `,
    )
    .join("");

  if (state.categoryAnalytics && state.categoryAnalytics.length) {
    html += `
      <div class="category-breakdown">
        <h4>Category Breakdown</h4>
        ${state.categoryAnalytics.map(a => `
          <div class="analytics-row">
            <span>${a.category} (${a.transaction_count} tx)</span>
            <strong>${formatMoney(a.total_amount)}</strong>
          </div>
        `).join("")}
      </div>
    `;
  }

  document.querySelector("#insightsList").innerHTML = html;
}

function buildInsights(totals, totalSpent) {
  if (!totalSpent) {
    return [
      {
        title: "Start with three expenses",
        body: "Add meals, transport, and course purchases to unlock useful student budget suggestions.",
      },
    ];
  }

  const entries = Object.entries(totals).sort((a, b) => b[1] - a[1]);
  const [topName, topAmount] = entries[0];
  const topPercent = Math.round((topAmount / totalSpent) * 100);
  const overspent = categories.find((category) => category.budget > 0 && (totals[category.name] || 0) > category.budget);
  const food = totals.Food || 0;
  const foodPercent = Math.round((food / totalSpent) * 100);
  const daysInPeriod = state.range === "custom" && state.customStartDate && state.customEndDate
    ? Math.max(1, Math.ceil((new Date(state.customEndDate) - new Date(state.customStartDate)) / (1000 * 60 * 60 * 24)))
    : (state.range === "week" ? 7 : 30);
  const dailyAverage = totalSpent / daysInPeriod;

  const insights = [
    {
      title: `You spend ${topPercent}% on ${topName.toLowerCase()} ${state.range}ly`,
      body: `Your biggest category is ${topName}. Set a soft cap before the next weekend to avoid surprise spending.`,
    },
    {
      title: `${formatMoney(dailyAverage)} daily pace`,
      body: `At this pace, your ${state.range}ly spending lands near ${formatMoney(totalSpent)}. Try a no-spend day to bend the trend.`,
    },
  ];

  if (foodPercent >= 30) {
    insights.unshift({
      title: `You spend ${foodPercent}% on food ${state.range}ly`,
      body: "Meal prep twice a week could free up money for savings without cutting social plans completely.",
    });
  }

  if (overspent) {
    insights.push({
      title: `${overspent.name} is over budget`,
      body: `You are ${formatMoney((totals[overspent.name] || 0) - overspent.budget)} above the planned limit.`,
    });
  } else {
    insights.push({
      title: "Budgets are still under control",
      body: "No category is over its limit in the selected period. Move a small surplus into your savings goal.",
    });
  }

  return insights.slice(0, 4);
}

function getFilteredExpenses() {
  if (state.range === "custom" && state.customStartDate && state.customEndDate) {
    const startDate = new Date(state.customStartDate);
    const endDate = new Date(state.customEndDate);
    // Include the end date by adding one day
    endDate.setDate(endDate.getDate() + 1);
    return state.expenses.filter((expense) => {
      const expenseDate = new Date(expense.date);
      return expenseDate >= startDate && expenseDate <= endDate;
    });
  }

  const limit = state.range === "week" ? 7 : 30;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - limit);
  return state.expenses.filter((expense) => !expense.deleted && new Date(expense.date) >= cutoff);
}

function getCategoryTotals(expenses) {
  return expenses.reduce((totals, expense) => {
    totals[expense.category] = (totals[expense.category] || 0) + expense.amount;
    return totals;
  }, {});
}

async function scanReceipt(file) {
  if (window.Tesseract) {
    try {
      const result = await window.Tesseract.recognize(file, "eng");
      const parsed = parseReceiptText(result.data.text, file.name);
      if (parsed.amount > 0) return { ...parsed, source: "OCR text" };
    } catch {
      return { ...simulateReceiptScan(file.name), source: "fallback scan" };
    }
  }

  return { ...simulateReceiptScan(file.name), source: "fallback scan" };
}

function parseReceiptText(text, fileName) {
  const normalized = `${text} ${fileName}`.toLowerCase();
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const merchant = lines.find((line) => merchantCategoryRules.some((rule) => rule.pattern.test(line)))
    || lines.find((line) => /[a-z]/i.test(line) && !/\b(total|visa|cash|change|tax)\b/i.test(line));
  const totalLine = lines.find((line) => /\b(total|amount|balance|due)\b/i.test(line));
  const amount = extractReceiptAmount(totalLine || text);
  const date = extractReceiptDate(text) || new Date().toISOString().slice(0, 10);
  const category = detectCategory(`${normalized} ${merchant || ""}`);

  return {
    name: merchant ? titleCase(merchant.slice(0, 34)) : receiptMerchantName(normalized, category.name),
    amount,
    category: category.name,
    date,
  };
}

function extractReceiptDate(text) {
  const cleaned = text.replace(/\r/g, "\n").toLowerCase();
  const datePatterns = [
    /(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})/, // yyyy-mm-dd
    /(\d{1,2})[-\/](\d{1,2})[-\/](\d{2,4})/, // dd/mm/yyyy or mm/dd/yyyy
  ];

  for (const pattern of datePatterns) {
    const match = cleaned.match(pattern);
    if (!match) continue;
    let year = match[1];
    let month = match[2];
    let day = match[3];

    if (year.length === 2) {
      year = `20${year}`;
    }
    if (pattern === datePatterns[1] && Number(month) > 12) {
      [day, month] = [month, day];
    }
    const iso = `${year.padStart(4, "0")}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
    if (!Number.isNaN(new Date(iso).getTime())) {
      return iso;
    }
  }
  return null;
}

function simulateReceiptScan(fileName) {
  const normalized = fileName.toLowerCase();
  const category = detectCategory(normalized);
  const amount = extractReceiptAmount(normalized) || Number((8 + Math.random() * 42).toFixed(2));

  return {
    name: receiptMerchantName(normalized, category.name),
    amount,
    category: category.name,
    date: new Date().toISOString().slice(0, 10),
  };
}

function detectCategory(text) {
  const normalizedText = text.toLowerCase();
  const match = merchantCategoryRules.find((rule) => rule.pattern.test(normalizedText));
  if (match) {
    const direct = categories.find((category) => category.name.toLowerCase() === match.category.toLowerCase());
    if (direct) return direct;
  }
  const directMatch = categories.find((category) => text.includes(category.name.toLowerCase()));
  if (directMatch) return directMatch;

  if (/cafe|pizza|market|grocery|restaurant|dining|meal|burger|coffee/.test(text)) return categories[0];
  if (/bus|train|uber|taxi|metro|fuel|transport/.test(text)) return categories[1];
  if (/book|stationery|library|course|print|lab/.test(text)) return categories[2];
  if (/rent|hostel|dorm|housing/.test(text)) return categories[3];
  if (/cinema|movie|game|club|ticket/.test(text)) return categories[4];
  if (/clinic|pharmacy|drug|health|medical/.test(text)) return categories[5];

  return categories[Math.floor(Math.random() * categories.length)];
}

function extractReceiptAmount(text) {
  const matches = [...text.matchAll(/(?:[$₦£€]\s*)?(\d{1,5})(?:[.,](\d{2}))?/g)];
  const amounts = matches
    .map((match) => Number(`${match[1]}.${match[2] || "00"}`))
    .filter((amount) => amount > 0 && amount < 100000);

  return amounts.length ? Math.max(...amounts) : 0;
}

function receiptMerchantName(fileName, category) {
  if (fileName.includes("netflix")) return "Netflix";
  if (fileName.includes("uber")) return "Uber";
  if (fileName.includes("taxi")) return "Taxi";
  if (fileName.includes("mtn")) return "MTN recharge";
  if (fileName.includes("cafe")) return "Campus Cafe";
  if (fileName.includes("book")) return "Bookstore";
  if (fileName.includes("bus") || fileName.includes("uber")) return "Transport receipt";
  if (fileName.includes("market")) return "Grocery market";
  return `${category} receipt`;
}

function titleCase(value) {
  return value
    .toLowerCase()
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase())
    .replace(/\s+/g, " ");
}

async function hydrateFromApi() {
  try {
    const data = await apiRequest("/api/state");
    apiOnline = true;
    currentProfile = data.profile;
    currentUserEmail = data.profile.email;
    localStorage.setItem(profileEmailKey, currentUserEmail);
    categories = data.categories.map(normalizeCategory);
    state = {
      ...state,
      categories,
      allowance: Number(data.profile.allowance),
      range: data.profile.preferred_range || "week",
      customStartDate: data.profile.custom_range_start || state.customStartDate,
      customEndDate: data.profile.custom_range_end || state.customEndDate,
      goal: normalizeGoal(data.goal),
      expenses: data.expenses.map(normalizeExpense),
      country: (data.settings && data.settings.country) || state.country,
      savingsCurrencies: (data.settings && data.settings.savings_currencies) || state.savingsCurrencies,
    };
    allowanceInput.value = state.allowance;
    document.querySelector("#goalName").value = state.goal.name;
    document.querySelector("#goalTarget").value = state.goal.target;
    document.querySelector("#goalSaved").value = state.goal.saved;
    document.querySelector("#accountLabel").textContent = data.profile.email;
    persist();

    // Sync range buttons and custom date inputs with backend data
    syncRangeButtons();
    syncCustomDateInputs();

    // Populate filter category dropdown
    populateFilterCategories();
    await fetchRecurringExpenses();
  } catch (error) {
    apiOnline = false;
    if (error.status === 403 && error.message === "Email verification required") {
      authMode = "verify";
      pendingVerificationEmail = pendingVerificationEmail || authEmail.value.trim();
      authMessage.textContent = "Verify your email before opening your dashboard.";
      renderAuthMode();
      showAuth();
    }
  }
}

async function saveSettingsToServer() {
  if (!apiOnline) return;
  clearTimeout(settingsSaveTimer);
  try {
    const payload = {
      country: state.country,
      savings_currencies: state.savingsCurrencies,
    };
    await apiRequest("/api/settings", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  } catch (err) {
    apiOnline = false;
  }
}

function populateFilterCategories() {
  if (!filterCategory) return;
  const currentValue = filterCategory.value;
  filterCategory.innerHTML = '<option value="">All categories</option>' +
    categories.map((category) => `<option value="${category.name}">${category.name}</option>`).join("");
  if (currentValue && categories.some((c) => c.name === currentValue)) {
    filterCategory.value = currentValue;
  }
}

function renderGreeting() {
  const greetingTarget = document.querySelector("#dashboardGreeting");
  if (!greetingTarget) return;

  const firstName = currentProfile?.first_name || currentProfile?.name?.split(" ")[0] || "";
  greetingTarget.textContent = firstName ? `${timeGreeting()}, ${firstName}` : timeGreeting();
}

function timeGreeting(date = new Date()) {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function togglePasswordVisibility() {
  const isPassword = authPassword.type === "password";
  authPassword.type = isPassword ? "text" : "password";
  passwordToggle.setAttribute("data-visible", String(isPassword));
  const label = isPassword ? "Hide password" : "Show password";
  passwordToggle.setAttribute("aria-label", label);
}

function applyFilters() {
  currentFilters = {
    search: filterSearch?.value?.trim() || "",
    category: filterCategory?.value || "",
    start_date: filterStartDate?.value || "",
    end_date: filterEndDate?.value || "",
    min_amount: parseFloat(filterMinAmount?.value) || 0,
    max_amount: parseFloat(filterMaxAmount?.value) || 0,
  };
  currentPage = 1;
  loadExpensesWithFilters();
}

function clearFilters() {
  if (filterSearch) filterSearch.value = "";
  if (filterCategory) filterCategory.value = "";
  if (filterStartDate) filterStartDate.value = "";
  if (filterEndDate) filterEndDate.value = "";
  if (filterMinAmount) filterMinAmount.value = "";
  if (filterMaxAmount) filterMaxAmount.value = "";
  currentFilters = {};
  currentPage = 1;
  loadExpensesWithFilters();
}

function goToPage(page) {
  currentPage = page;
  loadExpensesWithFilters();
}

async function loadExpensesWithFilters() {
  try {
    const params = new URLSearchParams({
      page: currentPage,
      per_page: itemsPerPage,
    });

    if (currentFilters.search) params.append("search", currentFilters.search);
    if (currentFilters.category) params.append("category", currentFilters.category);
    if (currentFilters.start_date) params.append("start_date", currentFilters.start_date);
    if (currentFilters.end_date) params.append("end_date", currentFilters.end_date);
    if (currentFilters.min_amount > 0) params.append("min_amount", currentFilters.min_amount);
    if (currentFilters.max_amount > 0) params.append("max_amount", currentFilters.max_amount);

    const data = await apiRequest(`/api/expenses?${params.toString()}`);

    paginationData = data.pagination;
    state.expenses = data.expenses;

    updatePaginationUI();
    render();
  } catch (error) {
    console.error("Failed to load filtered expenses:", error);
  }
}

function updatePaginationUI() {
  if (!paginationControls || !paginationData) return;

  paginationControls.classList.toggle("hidden", !paginationData || paginationData.total_pages <= 1);

  if (prevPageBtn) {
    prevPageBtn.disabled = !paginationData.has_prev;
  }
  if (nextPageBtn) {
    nextPageBtn.disabled = !paginationData.has_next;
  }
  if (pageInfo) {
    pageInfo.textContent = `Page ${paginationData.page} of ${paginationData.total_pages}`;
  }
}

function initTheme() {
  const savedTheme = localStorage.getItem(themeKey);
  if (savedTheme) {
    document.documentElement.setAttribute("data-theme", savedTheme);
  } else {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (prefersDark) {
      document.documentElement.setAttribute("data-theme", "dark");
    }
  }
}

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute("data-theme");
  if (currentTheme === "dark") {
    document.documentElement.removeAttribute("data-theme");
    localStorage.removeItem(themeKey);
  } else {
    document.documentElement.setAttribute("data-theme", "dark");
    localStorage.setItem(themeKey, "dark");
  }
}

// Listen for system theme changes
if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    const savedTheme = localStorage.getItem(themeKey);
    if (!savedTheme) {
      if (e.matches) {
        document.documentElement.setAttribute("data-theme", "dark");
      } else {
        document.documentElement.removeAttribute("data-theme");
      }
    }
  });
}

async function createExpense(expense) {
  if (!apiOnline) {
    return { ...expense, id: Date.now() };
  }

  try {
    const saved = await apiRequest("/api/expenses", {
      method: "POST",
      body: JSON.stringify(expense),
    });
    return normalizeExpense(saved);
  } catch {
    apiOnline = false;
    return { ...expense, id: Date.now() };
  }
}

async function updateGoal(goal) {
  if (!apiOnline) return goal;

  try {
    const saved = await apiRequest("/api/goal", {
      method: "PUT",
      body: JSON.stringify(goal),
    });
    return normalizeGoal(saved);
  } catch {
    apiOnline = false;
    return goal;
  }
}

async function updateCategoryBudget(category) {
  if (!apiOnline || !category.id) return category;

  try {
    const saved = await apiRequest(`/api/categories/${category.id}`, {
      method: "PATCH",
      body: JSON.stringify({ budget: category.budget }),
    });
    return normalizeCategory(saved);
  } catch {
    apiOnline = false;
    return category;
  }
}

async function updateProfile(allowance) {
  if (!apiOnline) return;

  try {
    await apiRequest("/api/profile", {
      method: "PATCH",
      body: JSON.stringify({ allowance }),
    });
  } catch {
    apiOnline = false;
  }
}

async function createRecurringExpense(payload) {
  try {
    const recurring = await apiRequest("/api/recurring-expenses", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showNotification(`Recurring expense "${recurring.name}" created`, "success");
    return recurring;
  } catch (error) {
    showNotification("Failed to create recurring expense", "error");
  }
}

async function apiRequest(path, options = {}) {
  const { skipAuth = false, headers: customHeaders = {}, ...fetchOptions } = options;
  const headers = { "Content-Type": "application/json", ...customHeaders };
  if (authToken && !skipAuth) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  let response;
  try {
    // Ensure cookies are sent so refresh-cookie flows work (same-origin during dev)
    const finalFetchOptions = { credentials: fetchOptions.credentials ?? "include", headers, ...fetchOptions };
    response = await fetch(`${apiBase}${path}`, finalFetchOptions);
  } catch (error) {
    throw new Error(`Could not reach the API at ${apiBase}. Make sure the backend is running.`);
  }

  if (!response.ok) {
    const message = await readApiError(response);
    // Try token refresh when receiving 401
    if (response.status === 401) {
      try {
        const refreshed = await refreshAccessToken();
        if (refreshed) {
          // retry original request once
          if (authToken && !skipAuth) headers.Authorization = `Bearer ${authToken}`;
          const retried = await fetch(`${apiBase}${path}`, { headers, ...fetchOptions });
          if (retried.ok) return retried.json();
        }
      } catch (err) {
        // fall through to clearing session below
      }

      // If we reach here, refresh failed — clear token and show message
      authToken = null;
      localStorage.removeItem(tokenKey);
      apiOnline = false;
      if (typeof showNotification === 'function') {
        showNotification("Session expired, please sign in again.", "error");
      }
    }

    const error = new Error(message || `API request failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }

  return response.json();
}

/**
 * Non-blocking notification helper
 * @param {string} message 
 * @param {'success' | 'error' | 'warning' | 'info'} type 
 */
function showNotification(message, type = "info") {
  let container = document.querySelector("#notificationContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "notificationContainer";
    document.body.appendChild(container);
  }
  
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  
  container.appendChild(toast);
  
  // Auto-remove after 4 seconds
  setTimeout(() => {
    toast.classList.add("fade-out");
    setTimeout(() => toast.remove(), 500);
  }, 4000);
}

/**
 * Toggle loading state on an element
 */
function toggleLoading(element, isLoading, originalText = "Submit") {
  if (!element) return;
  element.disabled = isLoading;
  element.innerHTML = isLoading ? '<span class="spinner"></span> Thinking...' : originalText;
}

function showSessionMessage(message, timeout = 10000) {
  showNotification(message, "info");
}

function hideSessionMessage() {
  if (!sessionMessageElem) return;
  sessionMessageElem.classList.add("hidden");
  sessionMessageElem.textContent = "";
}

async function readApiError(response) {
  try {
    const data = await response.json();
    return data.detail;
  } catch {
    return "";
  }
}

async function refreshAccessToken() {
  try {
    const res = await fetch(`${apiBase}/api/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },

function renderSpendingHeatmap(expenses) {
  const heatmap = document.querySelector("#spendingHeatmap");
  if (!heatmap) return;
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const totals = days.reduce((acc, day) => ({ ...acc, [day]: 0 }), {});
  expenses.forEach((expense) => {
    const day = new Date(expense.date).getDay();
    const label = days[(day + 6) % 7];
    totals[label] += expense.amount;
  });
  const max = Math.max(...Object.values(totals), 1);
  heatmap.innerHTML = days
    .map((day) => {
      const value = totals[day];
      const intensity = Math.min(0.9, value / max + 0.1);
      const background = `rgba(37, 99, 235, ${intensity})`;
      return `
        <div class="heatmap-cell" style="background:${background}; color: ${intensity > 0.55 ? '#fff' : 'inherit'};">
          <strong>${day}</strong>
          <span>${formatMoney(value)}</span>
        </div>
      `;
    })
    .join("");
}
    });
    if (!res.ok) {
      return false;
    }
    const data = await res.json();
    authToken = data.access_token;
    localStorage.setItem(tokenKey, authToken);
    apiOnline = true;
    return true;
  } catch (err) {
    return false;
  }
}

function normalizeCategory(category) {
  return {
    id: category.id,
    name: category.name,
    budget: Number(category.budget),
    color: category.color,
  };
}

function normalizeExpense(expense) {
  return {
    id: expense.id,
    name: expense.name,
    amount: Number(expense.amount),
    category: expense.category,
    date: expense.date,
    deleted: !!expense.deleted,
    deleted_at: expense.deleted_at || null,
  };
}

function normalizeGoal(goal) {
  return {
    id: goal.id,
    name: goal.name,
    target: Number(goal.target),
    saved: Number(goal.saved),
  };
}

function loadState(email = "") {
  if (!email) return structuredClone(defaultState);

  const saved = localStorage.getItem(stateStorageKey(email));
  if (!saved) return structuredClone(defaultState);

  try {
    return { ...structuredClone(defaultState), ...JSON.parse(saved) };
  } catch {
    return structuredClone(defaultState);
  }
}

function persist() {
  if (!currentUserEmail) return;

  localStorage.setItem(stateStorageKey(currentUserEmail), JSON.stringify(state));
}

function persistCategories() {
  state.categories = categories;
  persist();
}

function stateStorageKey(email) {
  return `${stateKeyPrefix}:${email.toLowerCase().trim()}`;
}

function daysAgo(days) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function sum(values) {
  return values.reduce((total, value) => total + value, 0);
}

function normalizeSavingsCurrencies() {
  if (!Array.isArray(state.savingsCurrencies) || !state.savingsCurrencies.length) {
    state.savingsCurrencies = [{ currency: currentCountryCurrency(), amount: 0, purpose: "" }];
  }

  return state.savingsCurrencies.map((entry) => ({
    currency: entry.currency || currentCountryCurrency(),
    amount: Number(entry.amount) || 0,
    purpose: entry.purpose || "",
  }));
}

function currentCountryCurrency() {
  return currencyConfig[state.country || "United States"]?.code || "USD";
}

function uniqueCurrencyCodes() {
  return [...new Set(Object.values(currencyConfig).map((config) => config.code))];
}

function currencyOptions(selected) {
  return uniqueCurrencyCodes()
    .map((code) => `<option value="${code}" ${code === selected ? "selected" : ""}>${code}</option>`)
    .join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatMoney(value, currencyOverride) {
  const country = state.country || "United States";
  const currency = currencyOverride || (currencyConfig[country]?.code || "USD");
  const locale = currencyConfig[country]?.locale || "en-US";
  
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: currency,
    maximumFractionDigits: value % 1 ? 2 : 0,
  }).format(value || 0);
}

function formatMoneyInCurrency(value, currencyCode) {
  const currency = currencyConfig[Object.keys(currencyConfig).find(key => currencyConfig[key].code === currencyCode)] || { locale: "en-US" };
  return new Intl.NumberFormat(currency.locale || "en-US", {
    style: "currency",
    currency: currencyCode,
    maximumFractionDigits: value % 1 ? 2 : 0,
  }).format(value || 0);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(value));
}
