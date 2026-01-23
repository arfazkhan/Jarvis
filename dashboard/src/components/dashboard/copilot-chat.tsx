
"use client";

import { useState, useRef, useEffect } from "react";
import { postChatQuery } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Send, Bot, User } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Message {
    role: "user" | "assistant";
    content: string;
}

export function CopilotChat() {
    const [messages, setMessages] = useState<Message[]>([
        { role: "assistant", content: "Hello! I'm ARVIS. How can I help with the building today?" }
    ]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollIntoView({ behavior: "smooth" });
        }
    }, [messages]);

    async function handleSend() {
        if (!input.trim()) return;

        const userMsg = input;
        setInput("");
        setMessages(prev => [...prev, { role: "user", content: userMsg }]);
        setLoading(true);

        try {
            const data = await postChatQuery(userMsg);
            setMessages(prev => [...prev, { role: "assistant", content: data.response || "Sorry, I didn't understand that." }]);
        } catch (err) {
            setMessages(prev => [...prev, { role: "assistant", content: "Error connecting to backend." }]);
        } finally {
            setLoading(false);
        }
    }

    return (
        <Card className="col-span-3 h-[600px] flex flex-col">
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Bot className="h-5 w-5" />
                    ARVIS Ops Copilot
                </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 flex flex-col gap-4 p-4 overflow-hidden">
                <ScrollArea className="flex-1 pr-4">
                    <div className="flex flex-col gap-4">
                        {messages.map((msg, i) => (
                            <div
                                key={i}
                                className={`flex gap-3 ${msg.role === "assistant" ? "flex-row" : "flex-row-reverse"
                                    }`}
                            >
                                <Avatar className="h-8 w-8">
                                    {msg.role === "assistant" ? (
                                        <AvatarFallback className="bg-primary text-primary-foreground"><Bot size={16} /></AvatarFallback>
                                    ) : (
                                        <AvatarFallback><User size={16} /></AvatarFallback>
                                    )}
                                </Avatar>
                                <div
                                    className={`rounded-lg p-3 text-sm ${msg.role === "assistant"
                                            ? "bg-muted text-foreground"
                                            : "bg-primary text-primary-foreground"
                                        }`}
                                >
                                    {msg.content}
                                </div>
                            </div>
                        ))}
                        {loading && (
                            <div className="flex gap-3">
                                <Avatar className="h-8 w-8">
                                    <AvatarFallback className="bg-primary text-primary-foreground"><Bot size={16} /></AvatarFallback>
                                </Avatar>
                                <div className="bg-muted rounded-lg p-3 text-sm">
                                    Thinking...
                                </div>
                            </div>
                        )}
                        <div ref={scrollRef} />
                    </div>
                </ScrollArea>

                <div className="flex gap-2 pt-4">
                    <Input
                        placeholder="Ask about alarms, energy, or equipment..."
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleSend()}
                        disabled={loading}
                    />
                    <Button size="icon" onClick={handleSend} disabled={loading}>
                        <Send className="h-4 w-4" />
                    </Button>
                </div>
            </CardContent>
        </Card>
    );
}
