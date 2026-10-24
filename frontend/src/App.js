import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { I18nProvider } from "@/context/I18nContext";
import { AuthProvider } from "@/context/AuthContext";
import { CartProvider } from "@/context/CartContext";
import { ThemeProvider, useTheme } from "@/context/ThemeContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppLayout } from "@/components/AppLayout";
import { AdminLayout } from "@/components/AdminLayout";
import { VendorLayout, useVendor } from "@/components/VendorLayout";

import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
import AdminSecureLogin from "@/pages/AdminSecureLogin";
import Register from "@/pages/Register";
import { LoginOtp, ForgotPassword } from "@/pages/AuthExtras";
import Dashboard from "@/pages/Dashboard";
import Products from "@/pages/Products";
import ProductDetail from "@/pages/ProductDetail";
import Cart from "@/pages/Cart";
import Checkout from "@/pages/Checkout";
import PaymentSuccess from "@/pages/PaymentSuccess";
import PaymentCancel from "@/pages/PaymentCancel";
import Orders from "@/pages/Orders";
import OrderDetail from "@/pages/OrderDetail";
import Wallet from "@/pages/Wallet";
import Referral from "@/pages/Referral";
import Notifications from "@/pages/Notifications";
import Profile from "@/pages/Profile";
import Rewards from "@/pages/Rewards";

import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminUsers from "@/pages/admin/AdminUsers";
import AdminProducts from "@/pages/admin/AdminProducts";
import AdminOrders from "@/pages/admin/AdminOrders";
import AdminReports from "@/pages/admin/AdminReports";
import AdminSettings from "@/pages/admin/AdminSettings";
import AdminAuditLogs from "@/pages/admin/AdminAuditLogs";
import Legal from "@/pages/Legal";
import Withdrawals from "@/pages/Withdrawals";
import AdminWithdrawals from "@/pages/admin/AdminWithdrawals";
import AdminVendors from "@/pages/admin/AdminVendors";
import AdminVendorCreate from "@/pages/admin/AdminVendorCreate";
import VendorDashboard from "@/pages/vendor/VendorDashboard";
import VendorProducts from "@/pages/vendor/VendorProducts";
import VendorOrders from "@/pages/vendor/VendorOrders";
import VendorProfile from "@/pages/vendor/VendorProfile";
import VendorInventory from "@/pages/vendor/VendorInventory";
import VendorDispatch from "@/pages/vendor/VendorDispatch";
import VendorReturns from "@/pages/vendor/VendorReturns";
import VendorAnalytics from "@/pages/vendor/VendorAnalytics";
import VendorReports from "@/pages/vendor/VendorReports";
import VendorEarnings from "@/pages/vendor/VendorEarnings";
import VendorShipping from "@/pages/vendor/VendorShipping";
import { PendingApproval } from "@/components/vendor/PendingApproval";
import VendorAdvancement from "@/pages/vendor/VendorAdvancement";
import VendorFinance from "@/pages/vendor/VendorFinance";
import VendorCod from "@/pages/vendor/VendorCod";
import VendorNotifications from "@/pages/vendor/VendorNotifications";
import VendorSupport from "@/pages/vendor/VendorSupport";
import VendorSecurity from "@/pages/vendor/VendorSecurity";

function App() {
  return (
    <I18nProvider>
      <ThemeProvider>
        <AuthProvider>
          <CartProvider>
            <ThemedToaster />
            <BrowserRouter>
              <AppRoutes />
            </BrowserRouter>
          </CartProvider>
        </AuthProvider>
      </ThemeProvider>
    </I18nProvider>
  );
}

// Toasts follow the light/dark theme and use the glass styling.
// Vendor data pages need an approved vendor account. Until then the page explains what is pending, inside the portal.
function VendorGate({ children }) {
  const { vendor } = useVendor();
  if (vendor === null) return null;
  return vendor && vendor.status === "approved" ? children : <PendingApproval vendor={vendor} />;
}
function VendorHome() {
  return <VendorGate><VendorDashboard /></VendorGate>;
}

function ThemedToaster() {
  const { theme } = useTheme();
  return (
    <Toaster position="top-center" richColors theme={theme} closeButton
      toastOptions={{ className: "!rounded-2xl !border !border-white/15 !backdrop-blur-xl !shadow-2xl" }} />
  );
}

// Synchronously intercept the Google OAuth return (session_id in the URL fragment) BEFORE
// ProtectedRoute runs, otherwise the user gets bounced to /login before the session exchange.
function AppRoutes() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) return <AuthCallback />;
  return (
              <Routes>
                <Route path="/" element={<Landing />} />
                <Route path="/login" element={<Login />} />
                <Route path="/admin-secure-login" element={<AdminSecureLogin />} />
                <Route path="/register" element={<Register />} />
                <Route path="/login-otp" element={<LoginOtp />} />
                <Route path="/forgot" element={<ForgotPassword />} />
                <Route path="/legal/:slug" element={<Legal />} />
                <Route path="/payment/success" element={<ProtectedRoute><PaymentSuccess /></ProtectedRoute>} />
                <Route path="/payment/cancel" element={<ProtectedRoute><PaymentCancel /></ProtectedRoute>} />

                <Route path="/app" element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
                  <Route index element={<Navigate to="/app/dashboard" replace />} />
                  <Route path="dashboard" element={<Dashboard />} />
                  <Route path="products" element={<Products />} />
                  <Route path="products/:id" element={<ProductDetail />} />
                  <Route path="cart" element={<Cart />} />
                  <Route path="checkout" element={<Checkout />} />
                  <Route path="orders" element={<Orders />} />
                  <Route path="orders/:id" element={<OrderDetail />} />
                  <Route path="rewards" element={<Rewards />} />
                  <Route path="wallet" element={<Wallet />} />
                  <Route path="withdrawals" element={<Withdrawals />} />
                  <Route path="referral" element={<Referral />} />
                  <Route path="notifications" element={<Notifications />} />
                  <Route path="profile" element={<Profile />} />
                </Route>

                <Route path="/admin" element={<ProtectedRoute admin><AdminLayout /></ProtectedRoute>}>
                  <Route index element={<AdminDashboard />} />
                  <Route path="users" element={<AdminUsers />} />
                  <Route path="products" element={<AdminProducts />} />
                  <Route path="orders" element={<AdminOrders />} />
                  <Route path="withdrawals" element={<AdminWithdrawals />} />
                  <Route path="vendors" element={<AdminVendors />} />
                  <Route path="vendors/new" element={<AdminVendorCreate />} />
                  <Route path="reports" element={<AdminReports />} />
                  <Route path="settings" element={<AdminSettings />} />
                  <Route path="audit" element={<AdminAuditLogs />} />
                </Route>

                <Route path="/vendor" element={<ProtectedRoute vendor><VendorLayout /></ProtectedRoute>}>
                  <Route index element={<Navigate to="dashboard" replace />} />
                  <Route path="dashboard" element={<VendorHome />} />
                  <Route path="orders" element={<VendorGate><VendorOrders /></VendorGate>} />
                  <Route path="products" element={<VendorGate><VendorProducts /></VendorGate>} />
                  <Route path="inventory" element={<VendorGate><VendorInventory /></VendorGate>} />
                  <Route path="dispatch" element={<VendorGate><VendorDispatch /></VendorGate>} />
                  <Route path="returns" element={<VendorGate><VendorReturns /></VendorGate>} />
                  <Route path="analytics" element={<VendorGate><VendorAnalytics /></VendorGate>} />
                  <Route path="reports" element={<VendorGate><VendorReports /></VendorGate>} />
                  <Route path="advancement" element={<VendorGate><VendorAdvancement /></VendorGate>} />
                  <Route path="finance" element={<VendorGate><VendorFinance /></VendorGate>} />
                  <Route path="earnings" element={<VendorGate><VendorEarnings /></VendorGate>} />
                  <Route path="shipping" element={<VendorGate><VendorShipping /></VendorGate>} />
                  <Route path="cod" element={<VendorGate><VendorCod /></VendorGate>} />
                  <Route path="notifications" element={<VendorGate><VendorNotifications /></VendorGate>} />
                  <Route path="support" element={<VendorGate><VendorSupport /></VendorGate>} />
                  <Route path="security" element={<VendorSecurity />} />
                  <Route path="profile" element={<VendorProfile />} />
                </Route>

                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
  );
}

export default App;
