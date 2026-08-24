import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { I18nProvider } from "@/context/I18nContext";
import { AuthProvider } from "@/context/AuthContext";
import { CartProvider } from "@/context/CartContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppLayout } from "@/components/AppLayout";
import { AdminLayout } from "@/components/AdminLayout";

import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
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
import Team from "@/pages/Team";
import Kyc from "@/pages/Kyc";
import Withdrawals from "@/pages/Withdrawals";
import Notifications from "@/pages/Notifications";
import Profile from "@/pages/Profile";

import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminUsers from "@/pages/admin/AdminUsers";
import AdminProducts from "@/pages/admin/AdminProducts";
import AdminOrders from "@/pages/admin/AdminOrders";
import AdminKyc from "@/pages/admin/AdminKyc";
import AdminWithdrawals from "@/pages/admin/AdminWithdrawals";
import AdminCommissions from "@/pages/admin/AdminCommissions";
import AdminReports from "@/pages/admin/AdminReports";
import AdminSettings from "@/pages/admin/AdminSettings";
import AdminAuditLogs from "@/pages/admin/AdminAuditLogs";

function App() {
  return (
    <I18nProvider>
      <AuthProvider>
        <CartProvider>
          <Toaster position="top-center" richColors />
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/login-otp" element={<LoginOtp />} />
              <Route path="/forgot" element={<ForgotPassword />} />
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
                <Route path="wallet" element={<Wallet />} />
                <Route path="referral" element={<Referral />} />
                <Route path="team" element={<Team />} />
                <Route path="kyc" element={<Kyc />} />
                <Route path="withdrawals" element={<Withdrawals />} />
                <Route path="notifications" element={<Notifications />} />
                <Route path="profile" element={<Profile />} />
              </Route>

              <Route path="/admin" element={<ProtectedRoute admin><AdminLayout /></ProtectedRoute>}>
                <Route index element={<AdminDashboard />} />
                <Route path="users" element={<AdminUsers />} />
                <Route path="products" element={<AdminProducts />} />
                <Route path="orders" element={<AdminOrders />} />
                <Route path="kyc" element={<AdminKyc />} />
                <Route path="withdrawals" element={<AdminWithdrawals />} />
                <Route path="commissions" element={<AdminCommissions />} />
                <Route path="reports" element={<AdminReports />} />
                <Route path="settings" element={<AdminSettings />} />
                <Route path="audit" element={<AdminAuditLogs />} />
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </CartProvider>
      </AuthProvider>
    </I18nProvider>
  );
}

export default App;
