
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';

import Admin from './pages/Admin';
import AdminPasswordReset from './pages/admin/AdminPasswordReset';
import { recoveryCallback } from './pages/admin/passwordRecovery';
import Visitor from './pages/Visitor';
import Study from './pages/Study';

function RedirectRecovery({ children }) {
  const { search, hash } = useLocation();
  if (recoveryCallback({ search, hash }).kind !== 'none') {
    return <Navigate to={{ pathname: '/admin/reset-password', search, hash }} replace />;
  }
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RedirectRecovery><Navigate to="/visitor" replace /></RedirectRecovery>} />
        <Route path="/admin" element={<RedirectRecovery><Admin /></RedirectRecovery>} />
        <Route path="/admin/reset-password" element={<AdminPasswordReset />} />
        <Route path="/admin/preview" element={<Admin preview />} />
        <Route path="/visitor" element={<Visitor />} />
        <Route path="/study" element={<Study />} />
      </Routes>
    </BrowserRouter>
  );
}
