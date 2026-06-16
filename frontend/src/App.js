import "./App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import Home from "./pages/Home";
import Room from "./pages/Room";
import Draft from "./pages/Draft";
import Simulation from "./pages/Simulation";

export default function App() {
  return (
    <div className="relative min-h-screen overflow-x-hidden">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/sala/:code" element={<Room />} />
          <Route path="/draft/:code" element={<Draft />} />
          <Route path="/jogo/:code" element={<Simulation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster
        position="top-center"
        toastOptions={{
          style: {
            background: "rgba(18,25,38,0.96)",
            color: "#FFFFFF",
            border: "1px solid rgba(57,255,20,0.45)",
            fontFamily: "'Oswald', sans-serif",
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            fontSize: "12px",
          },
        }}
      />
    </div>
  );
}
