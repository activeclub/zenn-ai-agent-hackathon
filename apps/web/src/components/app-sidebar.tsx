"use client";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { GalleryVerticalEnd } from "lucide-react";
import { NavUser } from "./nav-user";
import { NavSecondary } from "./nav-secondary";
import { useEffect, useState } from "react";
import { API_BASE_URL } from "@/config";
import { GetUser, User } from "@/app/api";

export function AppSidebar() {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    (async () => {
      const ret = await fetch(`${API_BASE_URL}/api/users/id`, {
        method: "GET",
      });
      const { data } = (await ret.json()) as GetUser;
      setUser(data);
    })();
  }, []);

  return (
    <Sidebar>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>
            <a
              href="#"
              className="flex items-center gap-2 self-center font-medium"
            >
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <GalleryVerticalEnd className="size-4" />
              </div>
              Wondy
            </a>
          </SidebarGroupLabel>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>Today</SidebarGroupLabel>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton asChild>
                <a href="#">
                  <span>◯◯のはなし</span>
                </a>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
        {user && <NavSecondary user={user} />}
      </SidebarContent>
      <SidebarFooter>{user && <NavUser user={user} />}</SidebarFooter>
    </Sidebar>
  );
}
